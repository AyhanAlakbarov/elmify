"""Vouching by link: deterministic, one hop, part-of only (spec §5.3).

A body no authority names -- a constituent institute, a joint-venture campus --
is RECOGNISED(vouched_by_link) when a RECOGNISED body's own main host links to
it from a structural position. The candidate's link only says where to look;
the recogniser's reverse link is the evidence. No model call, and a body
admitted this way vouches for nothing.

Worst case, 21 fetches per candidate: 2 tries at its homepage, 3 of its about
pages, 3 recognisers x 2 homepage tries, and 10 structural pages shared by all
recognisers (`MAX_STRUCTURAL_PAGES`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit

import lxml.etree
import lxml.html

from .fetch import fetch_page
from .fetch.types import FetchedPage
from .hosts import is_hosting_platform, registrable_domain
from .provenance import Reason
from .recognition import readable_page

#: Headings and link texts that mean "part of us", in the five languages the
#: spec names plus English. Matched as whole words. Pinned by
#: tests/research/test_vouch.py.
STRUCTURAL_TERMS: tuple[str, ...] = (
    "faculties", "faculty", "schools", "institutes", "campuses", "branches",
    "affiliated institutions",
    "fakültələr", "fakültə", "institutlar", "filiallar", "kampuslar",
    "fakülteler", "enstitüler", "yüksekokullar", "kampüsler",
    "fakultäten", "fachbereiche", "institute", "standorte",
    "facultés", "écoles", "instituts", "composantes",
    "단과대학", "대학원", "캠퍼스", "부속기관",
)
#: Where universities link bodies that are NOT part of them: agents, exchange
#: partners, sponsors. Matched as SUBSTRINGS, so German and Korean compounds
#: (Partnerhochschulen, 협력기관) exclude too: a false exclusion leaves a body
#: UNCONFIRMED and visible, a missed one admits a franchise college.
EXCLUDED_TERMS: tuple[str, ...] = (
    "partners", "partner", "agents", "representatives", "study abroad", "erasmus",
    "sponsors", "alumni", "events", "news",
    "tərəfdaşlar", "xəbərlər", "tədbirlər", "məzunlar",
    "ortaklar", "partnerler", "haberler", "etkinlikler", "mezunlar",
    "nachrichten", "veranstaltungen", "auslandsstudium",
    "partenaires", "actualités", "événements",
    "협력", "뉴스", "행사", "동문",
)
#: More sections that are not part-of, matched as whole words or phrases so
#: "event" leaves "eventually" alone. Not pinned with EXCLUDED_TERMS: these
#: are page furniture, not the spec's relationship pages.
_EXCLUDED_WORDS: tuple[str, ...] = ("event", "comment", "comments")
#: Words that describe a LIST -- a link column, a sidebar box, a staff
#: directory (English "faculty" also means teaching staff, whose personal
#: sites a directory links). Whole words, so "staff" leaves "staffing" alone.
#: They exclude only as a LABEL: a class, id, aria-label, heading, <title> or
#: path. In a link's own text they are names: "Institute of Human Resources",
#: "Command and Staff College".
_LIST_WORDS: tuple[str, ...] = (
    "useful links", "quick links", "resources", "external",
    "related sites", "related links", "recent posts",
    "faydalı keçidlər", "faydalı linkler", "nützliche links", "externe links",
    "liens utiles", "liens externes",
    "staff", "people", "directory", "교직원",
)
#: A label that is a body's name ("Faculty of External Relations") carries
#: list words without describing a list.
# ponytail: English "X of/for" names only, and a label splits only on / | : and
# dashes, so "Faculty of Arts staff directory" reads as a name. Widen when a
# real directory is measured slipping through.
_NAME = re.compile(
    r"(?:the )?(?:faculty|institute|school|college|academy|department|university) (?:of|for) "
)
MAX_STRUCTURAL_PAGES = 10
_MAX_RECOGNISERS = 3
#: Where a candidate says who it belongs to. A pointer only -- never evidence --
#: so a loose vocabulary costs a fetch, never an admission.
_ABOUT_TERMS = ("about", "haqq", "hakk", "über", "ueber", "propos", "소개")
_MAX_ABOUT_PAGES = 3
#: Site navigation only: a <header> or <footer> inside an <article> is a news
#: card's, and one inside <main> or <aside> is the content's.
_CONTAINER = (
    "(self::nav or self::header or self::footer or @role='navigation')"
    " and not(ancestor::article or ancestor::aside or ancestor::main)"
)
#: Where a followed link's heading is looked for: its own outermost section,
#: never elsewhere on the page ("Latest news" in <main> says nothing about a
#: footer link).
_SECTION = (
    "ancestor::*[self::nav or self::header or self::footer or self::section or self::aside"
    " or self::article or self::main or @role='navigation'][last()]"
)
_HEADING = "preceding::*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6][1]"

Fetch = Callable[..., FetchedPage]


@dataclass(frozen=True)
class VouchResult:
    vouch_url: str = ""
    recogniser_domain: str = ""
    failed: bool = False


def _folded(text: str) -> str:
    return " ".join(text.replace("_", " ").replace("-", " ").casefold().split())


def _is_structural(text: str) -> bool:
    folded = _folded(text)
    return (
        any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", folded) for term in STRUCTURAL_TERMS)
        and not _excluded(folded)
    )


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) for word in words)


def _excluded(text: str, *, label: bool = False) -> bool:
    """`label`: the text names a section or a page, not a link, so the list
    words count too -- in each part of it that is not a body's name."""
    folded = _folded(text)
    if any(term in folded for term in EXCLUDED_TERMS) or _has_word(folded, _EXCLUDED_WORDS):
        return True
    return label and any(
        not _NAME.match(part.strip()) and _has_word(part, _LIST_WORDS)
        for part in re.split(r"[/|:–—]", folded)
    )


def _document(page: FetchedPage) -> lxml.html.HtmlElement | None:
    # UTF-8 by default: given bytes and no <meta charset>, lxml reads Latin-1
    # and "Fakültələr" never matches its own term (cf. recognition._document).
    try:
        return lxml.html.document_fromstring(
            page.body, parser=lxml.html.HTMLParser(encoding="utf-8")
        )
    except (lxml.etree.ParserError, ValueError):
        return None


def _links(
    document: lxml.html.HtmlElement, base: str, xpath: str = "//a[@href]"
) -> list[tuple[str, lxml.html.HtmlElement]]:
    """Absolute http(s) links only: a mailto: address is not a link to a site."""
    found = []
    for anchor in document.xpath(xpath):
        url = urljoin(base, str(anchor.get("href")).strip())
        if urlsplit(url).scheme in ("http", "https"):
            found.append((url, anchor))
    return found


def _in_excluded_section(anchor: lxml.html.HtmlElement, container: lxml.html.HtmlElement) -> bool:
    """A partner-logo strip in a footer, or an "Erasmus partners" section on a
    faculties page, is a partners page by another name (spec §5.3): read the
    link's text, every enclosing class/id/label below <body> (a footer in a
    "partners-band" is still the band's), and the nearest heading before it
    inside `container`."""
    labels = []
    for node in anchor.iterancestors():
        if node.tag in ("body", "html"):
            break  # page-wide classes (Modernizr's "no-touchevents") label no section
        labels += [node.get("class") or "", node.get("id") or "", node.get("aria-label") or ""]
    heading = anchor.xpath(_HEADING)
    if heading and any(node is container for node in heading[0].iterancestors()):
        labels.append(heading[0].text_content())
    return _excluded(anchor.text_content()) or _excluded(" | ".join(labels), label=True)


def _heading(document: lxml.html.HtmlElement) -> str:
    h1 = document.xpath("//h1")
    return h1[0].text_content() if h1 else " ".join(document.xpath("//title/text()"))


def _main_host(url: str, domain: str) -> bool:
    """The recogniser's own voice: its bare or www host, no ~user path (spec §5.3)."""
    parts = urlsplit(url)
    on_host = (parts.hostname or "") in (domain, f"www.{domain}")
    return on_host and not unquote(parts.path).startswith("/~")


def _home(domain: str, fetch: Fetch) -> FetchedPage | None:
    """The homepage, through its www host when the bare one is unreadable."""
    for url in (f"https://{domain}/", f"https://www.{domain}/"):
        fetched = fetch(url, purpose="provenance")
        if readable_page(fetched):
            return fetched
    return None


def _about_pages(
    candidate: str, home: FetchedPage, document: lxml.html.HtmlElement, fetch: Fetch
) -> Iterator[tuple[lxml.html.HtmlElement, str]]:
    """The candidate's homepage, then up to `_MAX_ABOUT_PAGES` of its own
    "about" pages, each fetched only when the caller asks for the next one.
    One that is dead or lands elsewhere is skipped: that is an answer.
    Measured 2026-09-27: UFAZ's homepage links no parent; its "Establishment
    of UFAZ" page links ASOIU."""
    yield document, home.final_url
    about = [
        url for url, anchor in _links(document, home.final_url)
        if registrable_domain(url) == candidate
        and any(
            term in f"{urlsplit(url).path} {anchor.text_content()}".casefold()
            for term in _ABOUT_TERMS
        )
    ]
    for url in list(dict.fromkeys(about))[:_MAX_ABOUT_PAGES]:
        fetched = fetch(url, purpose="provenance")
        page = _document(fetched) if readable_page(fetched) else None
        if page is not None and registrable_domain(fetched.final_url) == candidate:
            yield page, fetched.final_url


def find_vouch(
    candidate: str, recognisers: Mapping[str, str], *, fetch: Fetch | None = None
) -> VouchResult:
    """`recognisers` maps each RECOGNISED body's bound domain to its reason code.

    The candidate's about pages are read, one at a time, whenever its homepage
    led to fewer than `_MAX_RECOGNISERS` recognisers and none vouched. `failed`
    means the candidate's or a recogniser's homepage could not be read and
    nothing vouched: a failed lookup, never evidence that the link is missing.
    A dead or off-site about or structural link is an answer, not a failure."""
    fetch = fetch or fetch_page
    home = _home(candidate, fetch)
    if home is None:
        return VouchResult(failed=True)
    document = _document(home)
    if document is None or registrable_domain(home.final_url) != candidate:
        return VouchResult()
    tried: list[str] = []
    budget = [MAX_STRUCTURAL_PAGES]
    failed = False
    for page, base in _about_pages(candidate, home, document, fetch):
        for url, _anchor in _links(page, base):
            recogniser = registrable_domain(url)
            if (
                len(tried) >= _MAX_RECOGNISERS
                or not recogniser
                or recogniser in tried
                or recogniser == candidate
                or is_hosting_platform(recogniser)
                or recognisers.get(recogniser) in (None, Reason.VOUCHED_BY_LINK)
            ):
                continue
            tried.append(recogniser)
            vouch_url, broke = _reverse_link(recogniser, candidate, fetch, budget)
            failed |= broke
            if vouch_url:
                return VouchResult(vouch_url=vouch_url, recogniser_domain=recogniser)
        if len(tried) >= _MAX_RECOGNISERS:
            break
    return VouchResult(failed=failed)


def _links_to(
    candidate: str, document: lxml.html.HtmlElement, base: str, *, homepage: bool
) -> bool:
    """Whether a structural position on this page links the candidate: the
    homepage's nav, header or footer, or anywhere on a structural page. A
    `ugc`/`nofollow` link is the site saying it does not stand behind it."""
    xpath = f"//*[{_CONTAINER}]//a[@href]" if homepage else "//a[@href]"
    for url, anchor in _links(document, base, xpath):
        rel = set((anchor.get("rel") or "").casefold().split())
        if registrable_domain(url) != candidate or rel & {"ugc", "nofollow"}:
            continue
        container = anchor.xpath(f"ancestor::*[{_CONTAINER}][last()]") if homepage else [document]
        if not _in_excluded_section(anchor, container[0]):
            return True
    return False


def _structural_links(document: lxml.html.HtmlElement, base: str, recogniser: str) -> list[str]:
    """Links worth following: the text says part-of, and neither the path nor
    the section it sits in says news, events or partners -- a headline such as
    "Institute of Petroleum signs MoU" reads as structural on its own."""
    return [
        url for url, anchor in _links(document, base)
        if _main_host(url, recogniser)
        and _is_structural(anchor.text_content())
        and not _excluded(urlsplit(url).path, label=True)
        and not _in_excluded_section(anchor, (anchor.xpath(_SECTION) or [document])[0])
    ]


def _structural_page(page: lxml.html.HtmlElement, url: str) -> bool:
    """Headed by a structural term, and neither that heading, its <title> nor
    the path it landed on says news, an event, partners or a list."""
    heading, title = _heading(page), " ".join(page.xpath("//title/text()"))
    return _is_structural(heading) and not _excluded(
        f"{heading} | {title} | {urlsplit(url).path}", label=True
    )


def _reverse_link(
    recogniser: str, candidate: str, fetch: Fetch, budget: list[int]
) -> tuple[str, bool]:
    """(the page on the recogniser's main host linking the candidate, whether
    its homepage could not be read). Every page must LAND on the main host: a
    parked domain's lander or an off-site redirect is not the recogniser
    speaking."""
    home = _home(recogniser, fetch)
    if home is None:
        return "", True
    document = _document(home)
    if document is None or not _main_host(home.final_url, recogniser):
        return "", False
    if _links_to(candidate, document, home.final_url, homepage=True):
        return home.final_url, False
    frontier = _structural_links(document, home.final_url, recogniser)
    seen = {home.final_url}
    for depth in (1, 2):
        following: list[str] = []
        for url in dict.fromkeys(frontier):
            if url in seen or budget[0] <= 0:
                continue
            seen.add(url)
            budget[0] -= 1
            fetched = fetch(url, purpose="provenance")
            on_host = readable_page(fetched) and _main_host(fetched.final_url, recogniser)
            page = _document(fetched) if on_host else None
            if page is None or not _structural_page(page, fetched.final_url):
                continue
            if _links_to(candidate, page, fetched.final_url, homepage=False):
                return fetched.final_url, False
            if depth == 1:
                following += _structural_links(page, fetched.final_url, recogniser)
        frontier = following
    return "", False
