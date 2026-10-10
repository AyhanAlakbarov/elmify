"""Reduce untrusted student input to typed identifiers.

This module is the trust boundary of the package. Its entire job is to ensure
that **no student-supplied string ever becomes a hostname or an unescaped path
segment**. We construct every URL; the student supplies only an owner and a
repository name, and both are validated against a strict pattern before they
leave here.

That is what makes the "one fixed trusted host" property real rather than
aspirational, and it is why validate_public_url and LocalEgressProxy are not
used in this package: the host is our constant, not their input. A URL naming
any other host is refused here and never fetched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

#: Deliberately narrower than what the forges accept. Anything outside this
#: cannot contain a path separator, a dot-segment or a percent-escape, which
#: is the property the whole module exists to guarantee.
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

#: The regex above still matches "." and "..", which read as the current or
#: parent directory once interpolated into a filesystem or URL path. Neither
#: forge permits an owner or repository name made only of dots, so refusing
#: it costs nothing legitimate and closes the traversal case the regex alone
#: does not.
_ALL_DOTS = re.compile(r"^\.+$")

#: A DOI is "10." then a registrant code then a slash then an opaque suffix.
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")

#: The suffix is interpolated raw into f"{_CROSSREF}{doi}" (publication.py) --
#: never urlencoded, because the registries expect the literal DOI in the
#: path. "#", "?" and "%" are how that path segment stops meaning what it
#: says (fragment, query string, or a percent-escape that decodes to one of
#: the others downstream), so they are refused here rather than trusted to
#: the constant host.
_DOI_FORBIDDEN_CHARS = re.compile(r"[#?%]")

#: VerifiedFact.source_ref is varchar(500) and a publication fact stores the
#: DOI as f"doi:{doi}" (facts.py::write_publication_fact); 200 leaves ample
#: room for that 4-char prefix under any real DOI (the longest observed in
#: this codebase is under 40 chars) while still refusing a suffix built to
#: be needlessly long.
_DOI_MAX_LENGTH = 200

_HOSTS = {"github.com": "github", "gitlab.com": "gitlab"}


class UnsupportedSource(ValueError):
    """The input names something this package will not fetch."""


@dataclass(frozen=True)
class RepoRef:
    host: str
    owner: str
    name: str


@dataclass(frozen=True)
class DoiRef:
    doi: str


#: An uploaded document is identified by its DocumentVersion row, not by a
#: pasted string, so it never reaches this module and has no type here.
SourceRef = RepoRef | DoiRef


def _is_safe_segment(value: str) -> bool:
    return bool(_SEGMENT.match(value)) and not _ALL_DOTS.match(value)


def _is_safe_doi(doi: str) -> bool:
    """No dot-segment, "#", "?" or "%", and a sane length.

    Mirrors _is_safe_segment's job for the repo path: a DOI whose suffix
    reads as ".." once split on "/" is exactly the traversal case
    _ALL_DOTS closes for owner/repo -- the DOI just has no equivalent
    guard today, despite this module's own docstring promising one.
    """
    if len(doi) > _DOI_MAX_LENGTH or _DOI_FORBIDDEN_CHARS.search(doi):
        return False
    _, _, suffix = doi.partition("/")
    return not any(segment in (".", "..") for segment in suffix.split("/"))


def _repo_from_url(raw: str) -> RepoRef:
    candidate = raw if "://" in raw else f"https://{raw}"
    parts = urlsplit(candidate)
    # userinfo and an explicit port are both ways to make a URL read as one
    # host and resolve as another; refuse rather than normalise. A malformed
    # port (e.g. "github.com:abc") makes urllib's own `.port` accessor raise
    # a bare ValueError before we ever get to compare it — that must still
    # come out as UnsupportedSource, not leak past this module's boundary.
    try:
        has_credentials_or_port = bool(parts.username or parts.password or parts.port)
    except ValueError as exc:
        raise UnsupportedSource("malformed port in the URL") from exc
    if has_credentials_or_port:
        raise UnsupportedSource("credentials or a port in the URL")
    host = _HOSTS.get(parts.hostname or "")
    if host is None:
        raise UnsupportedSource(f"not a supported host: {parts.hostname!r}")
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 2:
        raise UnsupportedSource("no owner and repository in the path")
    owner, name = segments[0], segments[1].removesuffix(".git")
    if not _is_safe_segment(owner) or not _is_safe_segment(name):
        raise UnsupportedSource("owner or repository name is not a plain segment")
    return RepoRef(host, owner, name)


def parse_source(raw: str) -> SourceRef:
    """Classify what the student pasted, or refuse it.

    Never guesses. An input this cannot classify is an error, not a fetch
    against a host we hope is safe.
    """
    text = raw.strip()
    if not text:
        raise UnsupportedSource("empty input")
    bare_doi = text.removeprefix("doi:").removeprefix("https://doi.org/")
    if _DOI.match(bare_doi) and _is_safe_doi(bare_doi):
        return DoiRef(bare_doi)
    if "github.com" in text or "gitlab.com" in text:
        return _repo_from_url(text)
    raise UnsupportedSource("not a recognised repository URL or DOI")
