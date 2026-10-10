"""Name -> site resolution (spec 6.5): v4's ladder with the six hold-out rules.

    rung 0  own-domain e-mail            (domains.email_domain, built)
    rung 1  Wikidata P856, exact match   (wikidata.find_item)
    rung 2  Tavily top 10 per variant -> tiered lexical score over the union
    rung 3  every pick below tier 3: the homepage title must name the same
            KIND of organisation and carry a distinctive token, the
            initials or the slug; the runner-up gets one try
    rung 4  Diffbot Enhance by name on the residue, through the same title check
    else    unresolved, with a reason (the table in the build plan)

Rank was the whole problem (12% -> 80% on the same responses, 4.13a); an
adjacent organisation is the whole residue (Carl-Zeiss-Stiftung -> zeiss.com,
Krupp -> villahuegel.de), which is why a title must agree on KIND and not just
contain a word. A failed fetch is unresolved, never accepted. Deterministic
throughout: no model call, nothing from a provider kept but a URL.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import lxml.html
from lxml import etree

from .classify import _USABLE
from .domains import email_domain, is_catalogue
from .fetch import SweepBudget, fetch_page
from .fetch.types import FetchedPage, Outcome
from .hosts import registrable_domain
from .models import ResolvedVia, UnresolvedReason
from .names import MIN_DISTINCTIVE, NameProfile, fold, inflected_kind, kind_of, profile, tokens
from .providers.base import ProviderUnavailable
from .vocabulary import Vocabulary
from .wikidata import WikidataMatch

_SPLIT = re.compile(r"[^a-z0-9]+")
#: The shortest piece rule 1 splits a label into. Shorter pieces ("de", "ev")
#: would let almost any label split into common words.
_MIN_PIECE = 3


@dataclass(frozen=True)
class Scored:
    url: str
    domain: str
    rank: int
    tier: int
    score: float
    #: Rule 1 fired: the label is only kind, place and common words.
    directory: bool


def _hit(token: str, flat: str) -> bool:
    """A distinctive token is in a label -- allowing a two-letter inflection
    on long tokens (kanserle -> kanser), the morphology v5 measured."""
    return token in flat or (len(token) >= 7 and token[:-2] in flat)


def _common_piece(piece: str, vocab: Vocabulary) -> bool:
    return bool(inflected_kind(piece, vocab)) or piece in vocab.geo or piece in vocab.generic


def _is_directory(flat: str, vocab: Vocabulary) -> bool:
    """Rule 1: a label that splits entirely into kind, place and common words
    names a directory, never an organisation (embassies, stiftungen, vakiflar)."""
    reachable = [False] * (len(flat) + 1)
    reachable[0] = True
    for end in range(_MIN_PIECE, len(flat) + 1):
        for start in range(0, end - _MIN_PIECE + 1):
            if reachable[start] and _common_piece(flat[start:end], vocab):
                reachable[end] = True
                break
    return reachable[len(flat)]


def _tier(flat: str, p: NameProfile, vocab: Vocabulary) -> int:
    if flat in p.slugs or flat in p.initials:
        return 3
    hits = [t for t in sorted(p.distinctive) if _hit(t, flat)]
    if len(hits) >= 2:
        return 2
    for token in hits:
        stem = token if token in flat else token[:-2]
        rest = flat.replace(stem, "", 1)
        # Token + the name's OWN org-word forms the label. Org-words only: a
        # city or a common word here was v2's one defect.
        if rest and kind_of(rest, vocab) & p.kinds:
            return 2
    if any(len(t) >= 6 for t in hits) or flat in p.distinctive:
        # "label = one token" lives here, demoted from its old promotion: it
        # fired for shared brand words (caritas.de, vakifbank, inonu.edu.tr)
        # one right against three wrong, so it is always title-gated.
        return 1
    return 0


def score_candidate(url: str, rank: int, p: NameProfile, vocab: Vocabulary) -> Scored | None:
    """One search result against a name. None = never a candidate at all (a
    host with no registrable domain to key it by). Aggregators never arrive:
    `TavilyProvider.candidates` drops them, so every caller of the lookup gets
    the same guard rather than each re-implementing it."""
    host = (urlsplit(url).hostname or "").lower()
    domain = registrable_domain(host) if host else ""
    if not domain:
        return None
    label, _, suffix = domain.partition(".")
    flat = "".join(t for t in _SPLIT.split(fold(label)) if t)
    tier = 3 if (flat in p.slugs or flat in p.initials) else None
    if tier is None and _is_directory(flat, vocab):
        return Scored(url, domain, rank, 0, 0.0, True)
    tier = tier if tier is not None else _tier(flat, p, vocab)
    if tier == 0:
        return Scored(url, domain, rank, 0, 0.0, False)
    score = float(tier)
    if any(w in flat for w in p.kind_words if len(w) >= MIN_DISTINCTIVE):
        score += 0.5
    if suffix.rsplit(".", 1)[-1] == vocab.cctld:
        score += 0.25
    return Scored(url, domain, rank, tier, score, False)


def ranked(lists: Sequence[Sequence[str]], p: NameProfile, vocab: Vocabulary) -> list[Scored]:
    """Every candidate from every variant's list, once per domain at its best
    rank, best score first and ties by rank (4.13a)."""
    first: dict[str, tuple[int, str]] = {}
    for results in lists:
        for rank, url in enumerate(results):
            domain = registrable_domain(url)
            if domain and (domain not in first or rank < first[domain][0]):
                first[domain] = (rank, url)
    scored = [
        s for rank, url in first.values()
        if (s := score_candidate(url, rank, p, vocab)) is not None
    ]
    return sorted(scored, key=lambda s: (-s.score, s.rank, s.domain))


def page_titles(body: bytes) -> tuple[str, ...]:
    """The page's own <title> and og:site_name -- origin bytes, read and dropped."""
    if not body.strip():
        return ()
    try:
        # UTF-8 first; anything else goes to libxml2 as BYTES, so the page's
        # own charset declaration is honoured (a windows-1254 "Vakfı" decoded
        # here as UTF-8 loses its kind word), and so does an XHTML page whose
        # <?xml encoding=...?> lxml refuses to parse from a str.
        try:
            tree = lxml.html.fromstring(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            tree = lxml.html.fromstring(body)
    except (etree.ParserError, ValueError):
        return ()
    found = []
    title = tree.findtext(".//title")
    if title:
        found.append(" ".join(title.split()))
    for meta in tree.iter("meta"):
        if (meta.get("property") or "").casefold() == "og:site_name" and meta.get("content"):
            found.append(" ".join(meta.get("content", "").split()))
    return tuple(t for t in found if t)


def title_agrees(p: NameProfile, titles: Sequence[str], vocab: Vocabulary) -> bool:
    """(a) the title names a kind the name names, and (b) it carries a
    distinctive token, the initials or the slug. (a) is what separates an
    adjacent body sharing a word -- "Kanser Savaşçıları" (Derneği) for
    Kanserle Savaş Vakfı -- and a name with no kind word never passes it,
    which is why one-token names never reach this check."""
    title_tokens = [t for title in titles for t in tokens(title)]
    title_kinds = {kind for t in title_tokens for kind in kind_of(t, vocab)}
    if not p.kinds & title_kinds:
        return False
    flat = "".join(title_tokens)
    return (
        any(_hit(t, flat) for t in p.distinctive)
        or any(i in title_tokens for i in p.initials)
        or any(s in flat for s in p.slugs)
    )


#: Names searched per entity -- native, English, Russian at most (rule 4).
_MAX_QUERY_VARIANTS = 3
#: Reasons the residue rung may still turn around. FETCH_FAILED is retried by
#: the fetch path first; ONE_TOKEN_NAME can never pass a kind check.
_DIFFBOT_REASONS = frozenset({
    UnresolvedReason.NO_CANDIDATE, UnresolvedReason.DIRECTORY, UnresolvedReason.TITLE_MISMATCH,
})


class CallBudgetSpent(RuntimeError):
    """A per-run provider cap ran out. The run stops; nothing is written."""


class FetchBudgetSpent(RuntimeError):
    """The sweep's fetch budget ran out mid-name. The run stops; nothing is written.

    `diffbot_asked` is set when it ran out verifying Diffbot's answer: that
    entity is already paid for, so the caller still owes the monthly meter.
    """

    diffbot_asked = False


@dataclass
class CallBudget:
    """A per-run cap on paid provider calls (Tavily, Diffbot). Spent before
    the call, so a cap of N never makes an N+1th."""

    limit: int
    spent: int = 0

    def spend(self) -> None:
        if self.spent >= self.limit:
            raise CallBudgetSpent(f"{self.spent} of {self.limit} calls spent")
        self.spent += 1


@dataclass(frozen=True)
class NameQuery:
    """One register row's question: its names (rule 4's variants), the
    country whose vocabulary reads them, and what the row already carries."""

    names: tuple[str, ...]
    country_code: str
    contact_email: str = ""
    #: False while the row was asked within Diffbot's retry window.
    allow_diffbot: bool = True

    def __post_init__(self) -> None:
        if not any(name.strip() for name in self.names):
            raise ValueError("a NameQuery needs at least one name")


@dataclass(frozen=True)
class Resolution:
    """What leaves the resolver: a registrable domain and the route, or a
    reason -- never a candidate list, snippet, title or provider score."""

    domain: str = ""
    via: str = ""
    reason: str = ""
    wikidata_qid: str = ""
    #: The names store after this run: the query's names plus Wikidata's labels.
    names: tuple[str, ...] = ()
    #: Diffbot was called for this name (whatever it answered) -- the monthly
    #: entity cap counts these.
    diffbot_asked: bool = False


@dataclass(frozen=True)
class _Found:
    domain: str = ""
    via: str = ""
    reason: str = ""


def _distinct(names: Sequence[str]) -> tuple[str, ...]:
    """Names in order, once per fold -- "HRANT DİNK VAKFI" and "Hrant Dink
    Vakfı" are one variant and one Tavily call, not two."""
    seen: dict[str, str] = {}
    for name in names:
        if name.strip():
            seen.setdefault(fold(name), name.strip())
    return tuple(seen.values())


@dataclass
class Resolver:
    vocabulary: Vocabulary
    candidates: Callable[[str], Sequence[str]]
    tavily: CallBudget
    fetch: Callable[..., FetchedPage] = fetch_page
    budget: SweepBudget | None = None
    wikidata: Callable[[Sequence[str]], WikidataMatch | None] | None = None
    #: The gate turns this off: its truth IS Wikidata's P856.
    use_wikidata_website: bool = True
    diffbot: Callable[[str], str] | None = None
    #: One homepage fetch per host per run: a host named by two entries' lists
    #: (or twice in one) costs one credit, and answers the same both times.
    _titles_by_host: dict[str, tuple[str, ...] | None] = field(default_factory=dict, repr=False)

    def resolve(self, query: NameQuery) -> Resolution:
        names = _distinct(query.names)
        if query.contact_email:
            domain = email_domain(query.contact_email)
            if domain:
                return Resolution(domain=domain, via=ResolvedVia.EMAIL, names=names)
        qid = ""
        if self.wikidata is not None:
            match = self.wikidata(names)
            if match is not None:
                qid, names = match.qid, _distinct((*names, *match.labels))
                if self.use_wikidata_website:
                    domain = next((d for url in match.websites
                                   if (d := registrable_domain(url)) and not is_catalogue(d)), "")
                    if domain:
                        return Resolution(domain, ResolvedVia.WIKIDATA, "", qid, names)
        p = profile(names, self.vocabulary)
        found = self._search(names, p)
        asked = False
        if (not found.domain and found.reason in _DIFFBOT_REASONS
                and self.diffbot is not None and query.allow_diffbot):
            asked, found = self._residue(names, p, found)
        return Resolution(found.domain, found.via, found.reason, qid, names, asked)

    def _search(self, names: tuple[str, ...], p: NameProfile) -> _Found:
        if p.one_token:
            return _Found(reason=UnresolvedReason.ONE_TOKEN_NAME)
        lists: list[Sequence[str]] = []
        for variant in names[:_MAX_QUERY_VARIANTS]:
            self.tavily.spend()
            lists.append(list(self.candidates(variant)))
        scored = ranked(lists, p, self.vocabulary)
        viable = [s for s in scored if s.score > 0]
        if not viable:
            directory = any(s.directory for s in scored)
            return _Found(reason=UnresolvedReason.DIRECTORY if directory
                          else UnresolvedReason.NO_CANDIDATE)
        if viable[0].tier == 3:
            return _Found(viable[0].domain, ResolvedVia.SEARCH_SLUG)
        return self._verify(viable[:2], p, ResolvedVia.SEARCH_TITLE)

    def _residue(
        self, names: tuple[str, ...], p: NameProfile, found: _Found
    ) -> tuple[bool, _Found]:
        """Rung 4. Diffbot's answer is a URL and goes through the same title
        check as a search pick; anything it cannot turn around leaves the
        search's own reason standing, except a failed fetch of its answer."""
        try:
            url = self.diffbot(names[0]) if self.diffbot else ""
        except CallBudgetSpent:
            return False, found
        except ProviderUnavailable:
            return True, found
        domain = registrable_domain(url) if url else ""
        if not domain or is_catalogue(domain):
            return True, found
        try:
            verified = self._verify(
                [Scored(url, domain, 0, 0, 0.0, False)], p, ResolvedVia.DIFFBOT
            )
        except FetchBudgetSpent as spent:
            spent.diffbot_asked = True
            raise
        if verified.domain or verified.reason == UnresolvedReason.FETCH_FAILED:
            return True, verified
        return True, found

    def _verify(self, candidates: Sequence[Scored], p: NameProfile, via: str) -> _Found:
        reasons: list[str] = []
        for s in candidates:
            titles = self._titles(s)
            if titles is None:
                reasons.append(UnresolvedReason.FETCH_FAILED)
            elif title_agrees(p, titles, self.vocabulary):
                return _Found(s.domain, via)
            else:
                reasons.append(UnresolvedReason.TITLE_MISMATCH)
        if UnresolvedReason.FETCH_FAILED in reasons:
            return _Found(reason=UnresolvedReason.FETCH_FAILED)
        return _Found(reason=UnresolvedReason.TITLE_MISMATCH)

    def _titles(self, s: Scored) -> tuple[str, ...] | None:
        """None = could not look; () = looked and it names nothing (or is elsewhere)."""
        host = (urlsplit(s.url).hostname or s.domain).lower()
        if host in self._titles_by_host:
            return self._titles_by_host[host]
        fetched = self.fetch(f"https://{host}/", purpose="read", tag="resolver-title",
                             budget=self.budget)
        if fetched.outcome == Outcome.BUDGET:
            raise FetchBudgetSpent(fetched.reason or "fetch budget spent")
        titles: tuple[str, ...] | None
        if fetched.outcome not in _USABLE:
            titles = None
        elif registrable_domain(fetched.final_url) != s.domain:
            titles = ()  # it landed on another body's site; its title is that body's
        else:
            titles = page_titles(fetched.body)
        self._titles_by_host[host] = titles
        return titles
