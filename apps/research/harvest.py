"""HTML harvesting for catalogue pages, on the stdlib parser.

No HTML-parsing dependency is added: catalogues only need anchors and page
text, and ``html.parser`` gives both. Nothing here interprets page content --
claims come from ``extraction.py`` alone.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .discovery import canonicalize_url
from .egress import FetchResult

#: Anchor labels that a catalogue uses for "the institution's own page".
#: Verified against DAAD detail pages 2026-08-27.
COURSE_WEBSITE_MARKERS = (
    "course website",
    "programme website",
    "program website",
    "official website",
)
COURSE_WEBSITE_CLASSES = ("visitcoursewebsite",)
_SKIPPED_TEXT_TAGS = frozenset({"script", "style", "noscript", "template"})
#: Chrome that changes between two fetches of an unchanged page: a rotating news
#: sidebar, a "last reviewed" footer, a session id in a form. Digesting it makes
#: every revalidation look like a change and re-runs extraction for nothing.
_BOILERPLATE_TAGS = frozenset({"nav", "header", "footer", "aside", "form"})


@dataclass(frozen=True)
class Anchor:
    href: str
    text: str
    css_class: str


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[Anchor] = []
        self._href: str | None = None
        self._class = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        self._href = attributes.get("href") or None
        self._class = attributes.get("class") or ""
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.anchors.append(Anchor(self._href, "".join(self._text).strip(), self._class))
            self._href = None


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TEXT_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TEXT_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.chunks.append(data.strip())


def anchors(body: bytes) -> list[Anchor]:
    parser = _AnchorParser()
    parser.feed(body.decode("utf-8", "replace"))
    parser.close()
    return parser.anchors


def page_text(body: bytes, *, limit: int = 20_000) -> str:
    """Every visible text node, chrome included, one per line.

    Its one caller is `recognition.names_institution`, which needs the header
    and footer -- where a site prints its own name -- and so cannot use
    `reader.readable_text`, which strips exactly those."""
    parser = _TextParser()
    parser.feed(body.decode("utf-8", "replace"))
    parser.close()
    return "\n".join(parser.chunks)[:limit]


def official_url_from_catalogue_page(page: FetchResult) -> str | None:
    """The institution's own page behind a catalogue record, or None.

    None is not a silent drop: the caller reports it in the run's `degraded`
    list (design §2.6; the name's own site is the resolver's question).
    Matching is by anchor label and class, off a short verified list, because a
    catalogue page links to dozens of unrelated hosts.

    This returns a fetch *target*, not a trusted source. The anchor is often a
    click-tracker, so what the lead is finally rebuilt from is the fetch's
    final_url, through ResearchLead.from_url -- that is where the catalogue
    guard runs (Task 12).

    # ponytail: label/class matching, one catalogue's vocabulary at a time; add
    # a per-catalogue selector to SeedCatalogue if a third catalogue needs one.
    """
    catalogue_host = urlsplit(page.final_url).hostname
    for anchor in anchors(page.body):
        label = anchor.text.casefold()
        css_class = anchor.css_class.casefold()
        matches = any(marker in label for marker in COURSE_WEBSITE_MARKERS) or any(
            name in css_class for name in COURSE_WEBSITE_CLASSES
        )
        if not matches:
            continue
        target = urljoin(page.final_url, anchor.href)
        if not target.startswith("https://"):
            continue
        if urlsplit(target).hostname == catalogue_host:
            continue
        try:
            return canonicalize_url(target)
        except ValueError:
            continue
    return None


class _ContentParser(HTMLParser):
    """Visible text with page chrome removed, and only inside <main> when present.

    Two passes are impossible on a streaming parser, so this collects both the
    whole-document text and the <main>-only text, and the caller picks. A page
    with no <main> still yields a digest -- most university CMSes have none.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.main_chunks: list[str] = []
        self._skip = 0
        self._in_main = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TEXT_TAGS or tag in _BOILERPLATE_TAGS:
            self._skip += 1
        elif tag == "main":
            self._in_main += 1

    def handle_endtag(self, tag: str) -> None:
        if (tag in _SKIPPED_TEXT_TAGS or tag in _BOILERPLATE_TAGS) and self._skip:
            self._skip -= 1
        elif tag == "main" and self._in_main:
            self._in_main -= 1

    def handle_data(self, data: str) -> None:
        if self._skip or not data.strip():
            return
        self.chunks.append(data.strip())
        if self._in_main:
            self.main_chunks.append(data.strip())


def content_digest(body: bytes) -> str:
    """A digest of what a reader would call the page, not of the bytes.

    ``persist_snapshot`` keeps hashing the raw response -- the evidence chain
    must cite what was actually retrieved. This is the separate question of
    whether the page *changed*, and hashing raw bytes answers it wrongly: a
    CSRF token or a rotating footer flips the digest and re-runs extraction on
    an unchanged programme page. Whitespace is normalised because a CMS reflow
    is not a change either.
    """
    parser = _ContentParser()
    parser.feed(body.decode("utf-8", "replace"))
    parser.close()
    chunks = parser.main_chunks or parser.chunks
    return hashlib.sha256(" ".join(" ".join(chunks).split()).encode("utf-8")).hexdigest()


def change_digest(content_type: str, body: bytes) -> str:
    """"Did this source change?", for every content type we archive.

    One function because two callers have to agree: `persist_snapshot` stores
    it and `read_program_page` compares against it, and while only one of them
    knew about PDFs, a PDF source never cache-hit -- every run re-read the
    document and paid for the model calls again.

    A PDF is hashed on its bytes: content_digest strips HTML chrome and means
    nothing here. Ceiling: a host that regenerates the file per request (an
    embedded timestamp) still re-reads every time, which is what every source
    did before. "" means "no answer", and a caller must treat it as a change.
    """
    if content_type == "text/html":
        return content_digest(body)
    if content_type == "application/pdf":
        return hashlib.sha256(body).hexdigest()
    return ""
