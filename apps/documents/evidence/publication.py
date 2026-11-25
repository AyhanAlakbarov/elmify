"""DOI -> bibliographic record, from Crossref then OpenAlex.

Everything here is mechanically derived: the registries are publisher-deposited
and re-checkable at any time, so no model reads anything on this path and the
resulting facts need no human confirmation.

Author ORDER is preserved exactly, because PublicationEntry.self_author_index
indexes into it. Which author is the applicant is never decided here -- name
matching cannot distinguish "Abdullayev O." from a co-author's similar surname,
which is why the schema stores an index the student picks.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

from anyascii import anyascii
from defusedxml import ElementTree as ET

from .sources import DoiRef
from .transport import Transport, Urllib3Transport

logger = logging.getLogger(__name__)

_CROSSREF = "https://api.crossref.org/works/"
_OPENALEX = "https://api.openalex.org/works/https://doi.org/"
_OPENALEX_SEARCH = "https://api.openalex.org/works?per-page=5&search="
_CROSSREF_SEARCH = "https://api.crossref.org/works?rows=3&query.bibliographic="
_HANDLE = "https://doi.org/api/handles/"
_ARXIV = "https://export.arxiv.org/api/query?id_list="
_ATOM = "{http://www.w3.org/2005/Atom}"

ARXIV_DOI_PREFIX = "10.48550/arxiv."
TITLE_SIMILARITY_FLOOR = 90
MIN_SUBTITLE_TOKENS = 4

RETRACTION_TYPES = frozenset(
    {"retraction", "partial_retraction", "withdrawal", "removal"}
)
NOTE_TYPES = frozenset(
    {"expression_of_concern", "correction", "corrigendum", "erratum", "addendum"}
)

_TURKIC_ASCII_MAP = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ə": "e",
        "Ə": "e",
        "ø": "o",
        "Ø": "o",
        "ł": "l",
        "Ł": "l",
        "ß": "ss",
        "đ": "d",
        "Đ": "d",
        "æ": "ae",
        "Æ": "ae",
    }
)
_GERMAN_UMLAUT_MAP = str.maketrans(
    {
        "ä": "ae",
        "Ä": "ae",
        "ö": "oe",
        "Ö": "oe",
        "ü": "ue",
        "Ü": "ue",
        "ß": "ss",
    }
)
_AZ_LATIN_TRANSLIT_MAP = str.maketrans(
    {
        "ə": "a",
        "Ə": "a",
        "ı": "i",
        "İ": "i",
        "ş": "sh",
        "Ş": "sh",
        "ç": "ch",
        "Ç": "ch",
        "ğ": "gh",
        "Ğ": "gh",
        "x": "kh",
        "X": "kh",
    }
)


class PublicationNotFound(LookupError):
    """Neither registry has a usable record for this DOI."""


class ChimericPublicationError(LookupError, ValueError):
    """The DOI resolves, but its title, authorship, or year contradicts the claim."""


@dataclass
class CitationCheck:
    doi: str
    claimed_title: str
    claimed_first_author: str = ""
    claimed_year: int | None = None
    status: str = "unverified"
    resolved_title: str | None = None
    resolved_first_author: str | None = None
    resolved_year: int | None = None
    retracted: bool = False
    preprint: bool = False
    chimeric: bool = False
    author_overlap: float | None = None
    sources: list[str] = field(default_factory=list)
    title_match: bool = True
    author_match: bool = True


@dataclass
class CrossrefFacts:
    retracted: bool = False
    update_notes: list[str] = field(default_factory=list)
    preprint_of: str | None = None
    has_preprint: str | None = None
    kind: str | None = None


@dataclass(frozen=True)
class PublicationRecord:
    doi: str
    title: str
    venue: str | None
    year: int | None
    #: The locator a citation needs. These reach PublicationEntry and the
    #: ledger, so a rendered citation can print "15 (6), 4739-4745" instead of
    #: a placeholder. `publisher` is deliberately still absent: a journal
    #: citation does not print it, so nothing would read it.
    volume: str | None
    issue: str | None
    pages: str | None
    authors: tuple[str, ...]
    work_type: str | None
    is_retracted: bool = False
    update_notes: tuple[str, ...] = ()
    is_preprint: bool = False
    published_doi: str | None = None
    has_preprint: str | None = None
    in_doaj: bool | None = None
    is_core: bool | None = None


PublicationMetadata = PublicationRecord


def _title_tokens(text: str, *, ascii_fold: bool = False) -> list[str]:
    if not text:
        return []
    if ascii_fold:
        folded = anyascii(text.translate(_TURKIC_ASCII_MAP))
        norm = unicodedata.normalize("NFKD", folded).encode("ascii", "ignore").decode()
        return re.findall(r"[a-z0-9]+", norm.lower())
    norm_u = unicodedata.normalize("NFKC", text).casefold()
    return re.findall(r"[^\W_]+", norm_u, flags=re.UNICODE)


def _token_sort_ratio(a: str, b: str) -> float:
    toks_u_a = sorted(_title_tokens(a, ascii_fold=False))
    toks_u_b = sorted(_title_tokens(b, ascii_fold=False))
    score_u = (
        SequenceMatcher(None, " ".join(toks_u_a), " ".join(toks_u_b)).ratio() * 100.0
        if toks_u_a and toks_u_b
        else 0.0
    )
    toks_a = sorted(_title_tokens(a, ascii_fold=True))
    toks_b = sorted(_title_tokens(b, ascii_fold=True))
    score_a = (
        SequenceMatcher(None, " ".join(toks_a), " ".join(toks_b)).ratio() * 100.0
        if toks_a and toks_b
        else 0.0
    )
    return max(score_u, score_a)


def title_matches(a: str, b: str) -> bool:
    """Fuzzy token-sort match, or a colon-subtitle suffix that appears as an
    unbroken word run in the longer title (books indexed as 'Series: Subtitle')."""
    if not a or not b:
        return False
    if _token_sort_ratio(a, b) >= TITLE_SIMILARITY_FLOOR:
        return True
    for ascii_fold in (False, True):
        toks_a = _title_tokens(a, ascii_fold=ascii_fold)
        toks_b = _title_tokens(b, ascii_fold=ascii_fold)
        short, long = (toks_a, toks_b) if len(toks_a) <= len(toks_b) else (toks_b, toks_a)
        if len(short) < MIN_SUBTITLE_TOKENS or len(short) == len(long):
            continue
        span = len(short)
        if any(long[i : i + span] == short for i in range(len(long) - span + 1)):
            return True
    return False


def _extract_raw_surname_token(name: str) -> str:
    if not name:
        return ""
    s = name.strip()
    if "," in s:
        s = s.split(",", 1)[0].strip()
    else:
        parts = [p for p in re.split(r"[\s.]+", s) if len(p) > 1]
        if not parts:
            parts = [p for p in re.split(r"[\s.]+", s) if p]
        s = parts[-1] if parts else s
    return s


def _ascii_letters(text: str) -> str:
    s = text.translate(_TURKIC_ASCII_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = anyascii(s)
    return re.sub(r"[^a-z]", "", s.lower())


def _surname(name: str) -> str:
    return _ascii_letters(_extract_raw_surname_token(name))


def name_token_variants(raw_token: str) -> set[str]:
    """Generate cross-script and transliteration variants for a single name token
    (Cyrillic/Greek/Arabic/CJK via `anyascii`, German umlauts `ae/oe/ue`, and
    Azerbaijani/Turkic `ə <-> a/e`, `x <-> kh`, `q <-> g/k`, `c <-> j/ch`,
    `ş <-> sh/s`, `ç <-> ch/c`, `ğ <-> gh/g`, `-iyev <-> -iev`)."""
    base = _ascii_letters(raw_token)
    if not base:
        return set()
    variants: set[str] = {base}

    # 1. German umlaut digraph expansion (ä->ae, ö->oe, ü->ue) and reverse folding
    umlaut_expanded = _ascii_letters(raw_token.translate(_GERMAN_UMLAUT_MAP))
    if umlaut_expanded:
        variants.add(umlaut_expanded)
    for v in list(variants):
        for digraph, vowel in (("ae", "a"), ("oe", "o"), ("ue", "u")):
            if digraph in v:
                variants.add(v.replace(digraph, vowel))

    # 2. Azerbaijani / Turkic transliteration expansion
    az_expanded = _ascii_letters(raw_token.translate(_AZ_LATIN_TRANSLIT_MAP))
    if az_expanded:
        variants.add(az_expanded)
    if "ə" in raw_token or "Ə" in raw_token:
        variants.add(_ascii_letters(raw_token.replace("ə", "a").replace("Ə", "A")))
        variants.add(_ascii_letters(raw_token.replace("ə", "e").replace("Ə", "E")))

    # Expand consonant & vowel transliteration equivalences across all current variants
    seed_Pool = list(variants)
    for v in seed_Pool:
        # x <-> kh (Orxan <-> Orkhan, Xalilov <-> Khalilov)
        if "x" in v:
            variants.add(v.replace("x", "kh"))
        if "kh" in v:
            variants.add(v.replace("kh", "x"))
        # q <-> g / k (Quliyev <-> Guliyev / Kuliyev)
        if v.startswith("q"):
            variants.add("g" + v[1:])
            variants.add("k" + v[1:])
        elif v.startswith(("g", "k")) and len(v) >= 4:
            variants.add("q" + v[1:])
        # c <-> j / ch (Cafarov / Ceferov <-> Jafarov / Chafarov)
        if v.startswith("c") and not v.startswith("ch"):
            variants.add("j" + v[1:])
            variants.add("ch" + v[1:])
        elif v.startswith("j"):
            variants.add("c" + v[1:])
        elif v.startswith("ch"):
            variants.add("c" + v[2:])
            variants.add("j" + v[2:])
        # sh <-> s, gh <-> g
        if "sh" in v:
            variants.add(v.replace("sh", "s"))
        if "gh" in v:
            variants.add(v.replace("gh", "g"))

    # Expand e <-> a in Turkic stems and -iyev <-> -iev Slavic/Turkic suffixes
    for v in list(variants):
        if v.startswith("el") and len(v) >= 5:
            variants.add("al" + v[2:])
        elif v.startswith("al") and len(v) >= 5:
            variants.add("el" + v[2:])
        if "e" in v and len(v) >= 5:
            variants.add(v.replace("e", "a"))
        if "a" in v and len(v) >= 5:
            variants.add(v.replace("a", "e"))

    for v in list(variants):
        if "iyev" in v:
            variants.add(v.replace("iyev", "iev"))
        if "iev" in v:
            variants.add(v.replace("iev", "iyev"))

    variants.discard("")
    return variants


_SURNAME_PARTICLES = frozenset(
    {"de", "del", "la", "las", "los", "da", "das", "do", "dos", "van", "von", "bin", "binti", "ibn"}
)


def _surname_variants(name: str) -> set[str]:
    """Return normalized surname plus cross-script, transliteration, and compound variants."""
    raw_surname = _extract_raw_surname_token(name)
    variants = set(name_token_variants(raw_surname))
    if name and "," not in name:
        parts = [
            p for p in re.split(r"[\s.]+", name.strip())
            if len(p) > 1 and p.lower() not in _SURNAME_PARTICLES
        ]
        if len(parts) >= 3:
            variants.update(name_token_variants(parts[-2]))
    return variants


def _given_matches_initial_or_name(a_raw: str, b_raw: str) -> bool:
    a_vars = name_token_variants(a_raw)
    b_vars = name_token_variants(b_raw)
    if not a_vars or not b_vars:
        return False
    if a_vars & b_vars:
        return True
    if len(a_raw) == 1:
        prefs = {v[0] for v in a_vars if v}
        return any(bv.startswith(p) for bv in b_vars for p in prefs)
    if len(b_raw) == 1:
        prefs = {v[0] for v in b_vars if v}
        return any(av.startswith(p) for av in a_vars for p in prefs)
    return False


def author_in_byline(claimed_author: str, authors: Sequence[str]) -> bool:
    """Whether `claimed_author` shares a normalized surname with any author in `authors`
    (supporting Western given-surname, Hispanic/Lusophone double surnames, and uncomma'd
    surname-first order such as 'Zhang Wei' vs 'Wei Zhang' / 'W. Zhang')."""
    want = _surname_variants(claimed_author)
    if not want:
        return False
    have: set[str] = set()
    for author in authors:
        have.update(_surname_variants(author))
    if want & have:
        return True
    if "," in claimed_author:
        return False
    claimed_parts = [p for p in re.split(r"[\s.]+", claimed_author.strip()) if p]
    if len(claimed_parts) < 2:
        return False
    claimed_first_vars = name_token_variants(claimed_parts[0])
    claimed_last_vars = name_token_variants(claimed_parts[-1])
    for author in authors:
        if "," in author:
            continue
        author_parts = [p for p in re.split(r"[\s.]+", author.strip()) if p]
        if len(author_parts) < 2:
            continue
        # Swapped (surname-first vs given-first): claimed[0] == author[-1] & claimed[-1] ~ author[0]
        if (
            claimed_first_vars & name_token_variants(author_parts[-1])
            and _given_matches_initial_or_name(claimed_parts[-1], author_parts[0])
        ):
            return True
        if (
            claimed_last_vars & name_token_variants(author_parts[0])
            and _given_matches_initial_or_name(claimed_parts[0], author_parts[-1])
        ):
            return True
    return False


def _linked_id(item: Mapping[str, Any]) -> str | None:
    if str(item.get("id-type") or "").lower() != "doi":
        return None
    raw = str(item.get("id") or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix) :]
    return raw.lower() or None


def crossref_facts_from_message(msg: Mapping[str, Any]) -> CrossrefFacts:
    facts = CrossrefFacts(kind=str(msg.get("type") or "").lower() or None)
    for key in ("update-to", "updated-by"):
        for u in msg.get(key) or ():
            if not isinstance(u, Mapping):
                continue
            utype = str(u.get("type") or "").lower().replace("-", "_").replace(" ", "_")
            if utype in RETRACTION_TYPES or "retract" in utype or "withdraw" in utype:
                facts.retracted = True
            elif utype in NOTE_TYPES and utype not in facts.update_notes:
                facts.update_notes.append(utype)
    rel = msg.get("relation")
    if isinstance(rel, Mapping):
        for item in rel.get("is-preprint-of") or ():
            if isinstance(item, Mapping) and (target := _linked_id(item)):
                facts.preprint_of = target
                break
        for item in rel.get("has-preprint") or ():
            if isinstance(item, Mapping) and (target := _linked_id(item)):
                facts.has_preprint = target
                break
    return facts


def source_labels(record: PublicationRecord) -> list[str]:
    """Venue and version hygiene tags (advisory, never a silent filter)."""
    labels: list[str] = []
    if record.is_preprint or record.doi.lower().startswith(
        ("10.1101/", "10.21203/", "10.26434/", ARXIV_DOI_PREFIX)
    ):
        if not record.published_doi:
            labels.append("preprint")
    if record.published_doi:
        labels.append(f"published (merged preprint {record.has_preprint or ''})".strip())
    for note in record.update_notes:
        labels.append(note)
    if (
        record.in_doaj is False
        and record.is_core is False
        and not record.is_preprint
        and record.venue
    ):
        labels.append("not in DOAJ or CORE")
    return labels


@dataclass
class _Registry:
    source: str
    title: str | None
    first_surname: str
    all_surnames: set[str]
    year: int | None
    retracted: bool = False
    preprint: bool = False


def _record_to_registry(source: str, record: PublicationRecord) -> _Registry:
    surnames: set[str] = set()
    for author in record.authors:
        surnames.update(_surname_variants(author))
    first = _surname(record.authors[0]) if record.authors else ""
    return _Registry(
        source=source,
        title=record.title,
        first_surname=first,
        all_surnames=surnames,
        year=record.year,
        retracted=record.is_retracted,
        preprint=record.is_preprint,
    )


def _judge(
    doi: str,
    claimed_title: str,
    claimed_first_author: str,
    claimed_year: int | None,
    regs: list[_Registry],
    claimed_authors: Sequence[str] | None = None,
) -> CitationCheck:
    retracted = any(r.retracted for r in regs)
    preprint = all(r.preprint for r in regs)
    sources = [r.source for r in regs]
    primary = regs[0]

    title_ok = (
        True
        if not claimed_title
        else any(r.title and title_matches(claimed_title, r.title) for r in regs)
    )
    if not any(r.title for r in regs):
        status = "unverified"
    elif not claimed_title or title_ok:
        status = "retracted" if retracted else "verified"
    else:
        status = "title_mismatch"

    claimed_variants = _surname_variants(claimed_first_author)
    author_ok = True
    overlap: float | None = None
    reg_all_surnames: set[str] = set()
    for r in regs:
        reg_all_surnames.update(r.all_surnames)

    if claimed_authors:
        matched_count = 0
        total_count = 0
        for a in claimed_authors:
            vars_a = _surname_variants(a)
            if not vars_a:
                continue
            total_count += 1
            if vars_a & reg_all_surnames:
                matched_count += 1
        if total_count and reg_all_surnames:
            overlap = matched_count / total_count
            if overlap == 0.0:
                author_ok = False
    elif claimed_variants and reg_all_surnames:
        author_ok = bool(claimed_variants & reg_all_surnames)
        overlap = 1.0 if author_ok else 0.0

    year_ok = True
    if claimed_year and any(r.year for r in regs):
        year_ok = any(r.year and abs(claimed_year - r.year) <= 1 for r in regs)

    chimeric = status == "title_mismatch" or (
        status == "verified" and (not author_ok or not year_ok)
    )
    if chimeric and status == "verified":
        status = "chimeric"

    return CitationCheck(
        doi=doi,
        claimed_title=claimed_title,
        claimed_first_author=claimed_first_author,
        claimed_year=claimed_year,
        status=status,
        resolved_title=primary.title,
        resolved_first_author=primary.first_surname or None,
        resolved_year=primary.year,
        retracted=retracted,
        preprint=preprint,
        chimeric=chimeric,
        author_overlap=overlap,
        sources=sources,
        title_match=title_ok,
        author_match=author_ok,
    )


def _from_crossref(doi: str, body: dict[str, Any]) -> PublicationRecord | None:
    message = body.get("message") or {}
    titles = message.get("title") or []
    authors = tuple(
        f"{entry.get('given', '')} {entry.get('family', '')}".strip()
        for entry in (message.get("author") or [])
    )
    if not titles or not any(authors):
        return None
    year: int | None = None
    for key in ("issued", "published-print", "published-online", "created"):
        parts = (message.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0] is not None:
            year = parts[0][0]
            break
    containers = message.get("container-title") or []
    hygiene = crossref_facts_from_message(message)
    work_type = message.get("type")
    return PublicationRecord(
        doi=doi,
        title=titles[0],
        venue=containers[0] if containers else None,
        year=year,
        volume=message.get("volume"),
        issue=message.get("issue"),
        pages=message.get("page"),
        authors=authors,
        work_type=work_type,
        is_retracted=hygiene.retracted,
        update_notes=tuple(hygiene.update_notes),
        is_preprint=(hygiene.kind == "posted-content"),
        published_doi=hygiene.preprint_of,
        has_preprint=hygiene.has_preprint,
    )


def _from_openalex(doi: str, body: dict[str, Any]) -> PublicationRecord | None:
    authors = tuple(
        (entry.get("author") or {}).get("display_name", "").strip()
        for entry in (body.get("authorships") or [])
    )
    title = body.get("title")
    if not title or not any(authors):
        return None
    biblio = body.get("biblio") or {}
    first, last = biblio.get("first_page"), biblio.get("last_page")
    source = (body.get("primary_location") or {}).get("source") or {}
    work_type = body.get("type")
    in_doaj_raw = source.get("is_in_doaj")
    is_core_raw = source.get("is_core")
    return PublicationRecord(
        doi=doi,
        title=title,
        venue=source.get("display_name"),
        year=body.get("publication_year"),
        volume=biblio.get("volume"),
        issue=biblio.get("issue"),
        # OpenAlex splits the range Crossref deposits as one string.
        pages=f"{first}-{last}" if first and last else None,
        authors=authors,
        work_type=work_type,
        is_retracted=bool(body.get("is_retracted")),
        is_preprint=(
            str(work_type or "").lower() == "preprint"
            or str(source.get("type") or "").lower() == "repository"
        ),
        in_doaj=in_doaj_raw if isinstance(in_doaj_raw, bool) else None,
        is_core=is_core_raw if isinstance(is_core_raw, bool) else None,
    )


def _from_arxiv_xml(doi: str, xml_text: str) -> PublicationRecord | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    entry = root.find(f"{_ATOM}entry")
    if entry is None or entry.findtext(f"{_ATOM}id") is None:
        return None
    title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
    if not title or title.lower() == "error":
        return None
    authors = tuple(
        (a.findtext(f"{_ATOM}name") or "").strip()
        for a in entry.findall(f"{_ATOM}author")
        if (a.findtext(f"{_ATOM}name") or "").strip()
    )
    if not any(authors):
        return None
    pub = (entry.findtext(f"{_ATOM}published") or "").strip()
    year = int(pub[:4]) if len(pub) >= 4 and pub[:4].isdigit() else None
    return PublicationRecord(
        doi=doi,
        title=title,
        venue="arXiv",
        year=year,
        volume=None,
        issue=None,
        pages=None,
        authors=authors,
        work_type="article",
        is_preprint=True,
    )


def _fetch_arxiv(doi: str, client: Any) -> PublicationRecord | None:
    if not doi.lower().startswith(ARXIV_DOI_PREFIX):
        return None
    arxiv_id = doi[len(ARXIV_DOI_PREFIX) :].strip()
    if not arxiv_id:
        return None
    url = f"{_ARXIV}{quote(arxiv_id)}"
    if hasattr(client, "get_bytes"):
        status, raw_bytes, _ = client.get_bytes(url, max_bytes=200_000)
        if status == 200 and raw_bytes:
            return _from_arxiv_xml(doi, raw_bytes.decode("utf-8", errors="replace"))
    status, body, _ = client.get_json(url)
    if status == 200 and isinstance(body, dict):
        if "xml" in body and isinstance(body["xml"], str):
            return _from_arxiv_xml(doi, body["xml"])
        return _from_openalex(doi, body) or _from_crossref(doi, body)
    return None


def _clean_doi(ref: DoiRef | str) -> str:
    if isinstance(ref, DoiRef):
        return ref.doi
    raw = ref.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix) :]
    return raw.strip()


def _validate_claims(
    record: PublicationRecord,
    *,
    claimed_title: str | None,
    claimed_author: str | None,
    claimed_year: int | None,
) -> None:
    if claimed_title is not None and not title_matches(claimed_title, record.title):
        raise ChimericPublicationError(
            f"DOI {record.doi!r} resolves to title {record.title!r}, not {claimed_title!r}"
        )
    if claimed_author is not None and not author_in_byline(claimed_author, record.authors):
        raise ChimericPublicationError(
            f"Author {claimed_author!r} not in byline {record.authors!r} for DOI {record.doi!r}"
        )
    if (
        claimed_year is not None
        and record.year is not None
        and abs(claimed_year - record.year) > 1
    ):
        raise ChimericPublicationError(
            f"DOI {record.doi!r} published in {record.year}, not {claimed_year}"
        )


def fetch_publication(
    ref: DoiRef | str,
    *,
    transport: Transport | None = None,
    claimed_title: str | None = None,
    claimed_author: str | None = None,
    claimed_year: int | None = None,
) -> PublicationRecord:
    """Crossref first; OpenAlex covers conference papers Crossref lacks.

    A record without a title or a byline is not returned. A publication whose
    authors we cannot read cannot support an authorship claim, and an error
    must never become a partial fact.
    """
    doi = _clean_doi(ref)
    client = transport if transport is not None else Urllib3Transport()
    status, body, _ = client.get_json(f"{_CROSSREF}{doi}")
    if status == 200:
        record = _from_crossref(doi, body)
        if record is not None:
            published_types = {
                "journal-article",
                "proceedings-article",
                "book-chapter",
                "article",
            }
            if (
                record.published_doi
                and record.published_doi.lower() != doi.lower()
                and record.work_type not in published_types
            ):
                pub_status, pub_body, _ = client.get_json(f"{_CROSSREF}{record.published_doi}")
                if pub_status == 200:
                    upgraded = _from_crossref(record.published_doi, pub_body)
                    if upgraded is not None:
                        record = PublicationRecord(
                            doi=upgraded.doi,
                            title=upgraded.title,
                            venue=upgraded.venue,
                            year=upgraded.year,
                            volume=upgraded.volume,
                            issue=upgraded.issue,
                            pages=upgraded.pages,
                            authors=upgraded.authors,
                            work_type=upgraded.work_type,
                            is_retracted=upgraded.is_retracted or record.is_retracted,
                            update_notes=upgraded.update_notes or record.update_notes,
                            is_preprint=False,
                            published_doi=record.published_doi,
                            has_preprint=doi,
                            in_doaj=upgraded.in_doaj,
                            is_core=upgraded.is_core,
                        )
            _validate_claims(
                record,
                claimed_title=claimed_title,
                claimed_author=claimed_author,
                claimed_year=claimed_year,
            )
            return record
        logger.warning("PublicationRecordIncomplete party=crossref status=200")
    elif status != 404:
        logger.warning("PublicationLookupDegraded party=crossref status=%d", status)
    status, body, _ = client.get_json(f"{_OPENALEX}{doi}")
    if status == 200:
        record = _from_openalex(doi, body)
        if record is not None:
            _validate_claims(
                record,
                claimed_title=claimed_title,
                claimed_author=claimed_author,
                claimed_year=claimed_year,
            )
            return record
        logger.warning("PublicationRecordIncomplete party=openalex status=200")
    elif status != 404:
        logger.warning("PublicationLookupDegraded party=openalex status=%d", status)
    if doi.lower().startswith(ARXIV_DOI_PREFIX):
        arxiv_record = _fetch_arxiv(doi, client)
        if arxiv_record is not None:
            _validate_claims(
                arxiv_record,
                claimed_title=claimed_title,
                claimed_author=claimed_author,
                claimed_year=claimed_year,
            )
            return arxiv_record
    raise PublicationNotFound(doi)


def _search_title_in_registries(
    client: Transport,
    title: str,
) -> list[_Registry]:
    """Tier-2 fallback: Search OpenAlex and Crossref by title when DOI is missing."""
    if not title or len(title.strip()) < 8:
        return []
    regs: list[_Registry] = []
    encoded = quote(title.strip())
    status, body, _ = client.get_json(f"{_OPENALEX_SEARCH}{encoded}")
    if status == 200 and isinstance(body, dict):
        for item in body.get("results") or ():
            if not isinstance(item, dict):
                continue
            cand_title = str(item.get("title") or item.get("display_name") or "")
            if title_matches(title, cand_title):
                oa_rec = _from_openalex(str(item.get("doi") or ""), item)
                if oa_rec is not None:
                    regs.append(_record_to_registry("openalex_search", oa_rec))
                    break
    if not regs:
        status, body, _ = client.get_json(f"{_CROSSREF_SEARCH}{encoded}")
        if status == 200 and isinstance(body, dict):
            msg = body.get("message")
            items = msg.get("items") if isinstance(msg, dict) else ()
            for item in items or ():
                if not isinstance(item, dict):
                    continue
                titles = item.get("title") or ()
                cand_title = str(titles[0]) if titles else ""
                if title_matches(title, cand_title):
                    cr_rec = _from_crossref(str(item.get("DOI") or ""), {"message": item})
                    if cr_rec is not None:
                        regs.append(_record_to_registry("crossref_search", cr_rec))
                        break
    return regs


def verify_publication(
    ref: DoiRef | str = "",
    *,
    claimed_title: str = "",
    claimed_first_author: str = "",
    claimed_authors: Sequence[str] | None = None,
    claimed_year: int | None = None,
    student_name: str = "",
    transport: Transport | None = None,
) -> CitationCheck:
    """2-tier publication verification across Crossref, OpenAlex, arXiv, and DOI Handle API."""
    doi = _clean_doi(ref) if ref else ""
    client = transport if transport is not None else Urllib3Transport()
    effective_first = claimed_first_author or student_name
    regs: list[_Registry] = []

    if doi:
        if doi.lower().startswith(ARXIV_DOI_PREFIX):
            ar_rec = _fetch_arxiv(doi, client)
            if ar_rec is not None:
                regs.append(_record_to_registry("arxiv", ar_rec))
        else:
            status, body, _ = client.get_json(f"{_CROSSREF}{doi}")
            if status == 200 and isinstance(body, dict):
                cr_rec = _from_crossref(doi, body)
                if cr_rec is not None:
                    regs.append(_record_to_registry("crossref", cr_rec))
        status, body, _ = client.get_json(f"{_OPENALEX}{doi}")
        if status == 200 and isinstance(body, dict):
            oa_rec = _from_openalex(doi, body)
            if oa_rec is not None:
                regs.append(_record_to_registry("openalex", oa_rec))
        if regs:
            return _judge(
                doi,
                claimed_title,
                effective_first,
                claimed_year,
                regs,
                claimed_authors=claimed_authors,
            )
        h_status, h_body, _ = client.get_json(f"{_HANDLE}{doi}")
        if h_status == 200 and isinstance(h_body, dict) and h_body.get("responseCode") == 1:
            return CitationCheck(
                doi=doi,
                claimed_title=claimed_title,
                claimed_first_author=effective_first,
                claimed_year=claimed_year,
                status="handle_only",
                sources=["handle"],
            )
        if not claimed_title:
            return CitationCheck(
                doi=doi,
                claimed_title=claimed_title,
                claimed_first_author=effective_first,
                claimed_year=claimed_year,
                status="not_found",
                title_match=False,
                author_match=False,
            )

    if claimed_title:
        search_regs = _search_title_in_registries(client, claimed_title)
        if search_regs:
            check = _judge(
                doi,
                claimed_title,
                effective_first,
                claimed_year,
                search_regs,
                claimed_authors=claimed_authors,
            )
            if doi and check.status == "verified":
                # Claimed DOI failed to resolve, but title matched a different record -> chimeric
                check.chimeric = True
                check.status = "chimeric"
            return check

    return CitationCheck(
        doi=doi,
        claimed_title=claimed_title,
        claimed_first_author=effective_first,
        claimed_year=claimed_year,
        status="not_found",
        title_match=False,
        author_match=False,
    )
