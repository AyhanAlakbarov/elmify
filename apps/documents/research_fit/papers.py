"""OpenAlex paper lookup for a site-confirmed faculty member (spec 2026-10-14 §6.1-6.2).

Why after site confirmation, never before: OpenAlex `last_known_institutions`
tracks an author's most recent indexed paper, not their current payroll (62%
institution accuracy in the 2026 audit; docs/research/2026-10-14-letter-story/
2026-10-14-professor-and-paper-discovery.md Q1b). The university's own page is
therefore the primary witness that the person is there today; OpenAlex supplies
one recent (last 3 years), non-retracted paper by that person at that
institution so a research-track letter can connect the applicant's anchor work
to a concrete published paper.

Privacy boundary: the query sent to `api.openalex.org` carries only the
already-guarded topic phrase (`guard_phrase`) and the target institution's
catalog name -- never student PII or raw profile text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from defusedxml import ElementTree as ET
from django.conf import settings
from django.core.cache import cache

from apps.documents.evidence.publication import name_token_variants
from apps.documents.evidence.transport import Urllib3Transport
from apps.research.egress import fetch_json_api

from .classify import _INACTIVE_PERSON_RE, ClassifiedSentence, entity_in_sentence
from .split import page_sentences

logger = logging.getLogger(__name__)

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
OPENALEX_AUTHORS_URL = "https://api.openalex.org/authors"
CROSSREF_WORKS_URL = "https://api.crossref.org/works/"
EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_DOI_URL_PREFIX = "https://doi.org/10.48550/arxiv."
PAPER_CACHE_TTL_SECONDS = 7 * 24 * 3600
_MAX_PAPER_AGE_YEARS = 6
_RECENT_BONUS_YEARS = 3
RECENT_YEARS = 4
RRF_K = 60
ORCID_RE = re.compile(r"(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", re.I)
OA_AUTHOR_RE = re.compile(r"(?:https?://openalex\.org/)?([Aa]\d{4,})")
_JATS_TAG_RE = re.compile(r"<[^>]+>")
_TRAINEE_PERSON_RE = re.compile(
    r"\b(?:"
    r"ph\.?d\.?\s*(?:student|candidate)|"
    r"doctoral\s+(?:student|candidate|researcher)|"
    r"master'?s\s+student|m\.?sc\.?\s+student|b\.?sc\.?\s+student|"
    r"graduate\s+student|undergraduate|student\s+assistant|"
    r"doktorand(?:in|en)?|promovend(?:us|a|i)?|doctorant(?:e|s)?|"
    r"doctorando|doctoranda|dottorando|dottoranda|"
    r"doktorant(?:ura)?|magistrant|"
    r"araştırma\s+görevlisi|arastirma\s+gorevlisi|"
    r"аспирант(?:ка)?|магистрант(?:ка)?|докторант(?:ка)?"
    r")\b",
    re.IGNORECASE,
)
_GROUP_STOP_WORDS = frozenset({
    "chair", "group", "laboratory", "department", "institute", "institut",
    "center", "centre", "research", "division", "unit", "faculty", "school",
    "section", "team", "working", "lehrstuhl", "fachgebiet", "abteilung",
})
_TITLE_PREFIX = re.compile(
    r"^(?:prof(?:essor)?|dr(?:\.-?ing)?|mr|ms|mrs|assoc(?:iate)?|asst|assistant|"
    r"ir|ing|univ|habil|rer|nat|phil|med|sc|h\.?c\.?|doç(?:ent)?|dos(?:ent)?|"
    r"проф(?:ессор)?|д-?р|доц(?:ент)?|акад(?:емик)?)"
    r"[.\-\s]+",
    re.IGNORECASE,
)
_NON_ALPHA = re.compile(r"[^\w\s-]", re.UNICODE)
_WORK_PHRASE_CUE_RE = re.compile(
    r"\b(?:"
    r"we\s+(?:show|propose|find|demonstrate|prove|derive|introduce|present|develop|establish|"
    r"argue|trace|reconstruct|critique|examine)|"
    r"results\s+(?:indicate|show|demonstrate)|"
    r"our\s+(?:results|method|approach|analysis|framework)\s+(?:shows?|demonstrates?|achieves?)|"
    r"this\s+(?:paper|study|work|article|book|chapter|monograph|essay)\s+"
    r"(?:presents|shows|proposes|demonstrates|introduces|argues|examines|traces|reconstructs|"
    r"critiques|analyzes|analyses|explores)|"
    r"wir\s+(?:zeigen|untersuchen|belegen|entwickeln|analysieren)|"
    r"diese\s+(?:arbeit|studie|untersuchung)\s+(?:zeigt|untersucht|analysiert)|"
    r"nous\s+(?:montrons|proposons|démontrons|analysons|étudions)|"
    r"cette\s+(?:étude|contribution)\s+(?:montre|analyse|examine|propose)|"
    r"(?:mostramos|proponemos|demostramos|analizamos)|"
    r"(?:mostriamo|proponiamo|dimostriamo|analizziamo)|"
    r"bu\s+(?:çalışmada|makalede|araştırmada)"
    r")\b",
    re.IGNORECASE,
)
_METHOD_OR_QUESTION_CUE_RE = re.compile(
    r"\b(?:"
    r"however|remains?\s+(?:a\s+)?(?:challenging|open|unresolved|unclear|difficult|limited)|"
    r"open\s+(?:question|problem|challenge)|bottleneck|limitation|"
    r"we\s+(?:formulate|model|combine|couple|bridge|investigate|examine|analyze|analyse)|"
    r"(?:by|via)\s+(?:combining|coupling|formulating|integrating|introducing)|"
    r"future\s+work|"
    r"at\s+issue\s+is\s+whether|central\s+question|unresolved\s+tension|"
    r"contests?\s+the\s+assumption|drawing\s+on\s+(?:archival|doctrinal|ethnographic)|"
    r"jedoch|bleibt\s+(?:offen|ungeklärt)|offene\s+frage|"
    r"cependant|demeure\s+ouverte|sin\s+embargo|tuttavia|bununla\s+birlikte"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PaperMatch:
    title: str
    year: int
    url: str
    finding: str
    author_role: str = "lead"
    method_or_question: str = ""
    active_topic: str = ""


@dataclass(frozen=True)
class TopicCount:
    topic_id: str
    display_name: str
    count: int
    subfield: str | None = None
    field: str | None = None
    domain: str | None = None


@dataclass(frozen=True)
class TopicSuggestion:
    topic_id: str
    display_name: str
    relationship: str  # "core" | "recent_shift" | "adjacent"
    career_count: int = 0
    recent_count: int = 0
    co_occurrence: int = 0
    shift: float = 0.0
    subfield: str | None = None
    field: str | None = None
    domain: str | None = None


PaperLookup = Callable[..., PaperMatch | None]


def classify_identifier(raw: str) -> tuple[str, str]:
    """Classify a researcher identifier into ('orcid' | 'openalex' | 'name', value)."""
    s = raw.strip()
    m = ORCID_RE.fullmatch(s)
    if m:
        return "orcid", m.group(1).upper()
    m = OA_AUTHOR_RE.fullmatch(s)
    if m:
        return "openalex", "A" + m.group(1)[1:]
    return "name", s


def recency_shift(
    career: Sequence[TopicCount], recent: Sequence[TopicCount]
) -> dict[str, tuple[int, int, float]]:
    """Map topic_id -> (career_count, recent_count, recent_share - career_share)."""
    c_total = sum(t.count for t in career) or 1
    r_total = sum(t.count for t in recent) or 1
    c_map = {t.topic_id: t.count for t in career}
    r_map = {t.topic_id: t.count for t in recent}
    out: dict[str, tuple[int, int, float]] = {}
    for tid in set(c_map) | set(r_map):
        cc = c_map.get(tid, 0)
        rc = r_map.get(tid, 0)
        out[tid] = (cc, rc, (rc / r_total) - (cc / c_total))
    return out


def rank_candidates(
    career_primary: Sequence[TopicCount],
    recent_primary: Sequence[TopicCount],
    co_occurring: Sequence[TopicCount] = (),
    *,
    limit: int = 10,
) -> list[TopicSuggestion]:
    """Rank a researcher's core, rising (recent_shift > 0), and adjacent OpenAlex topics."""
    shifts = recency_shift(career_primary, recent_primary)
    names = {
        t.topic_id: t.display_name
        for t in (*career_primary, *recent_primary, *co_occurring)
    }
    core_ids = {t.topic_id for t in career_primary[:5]}

    suggestions: list[TopicSuggestion] = []
    for t in career_primary[:5]:
        cc, rc, sh = shifts.get(t.topic_id, (t.count, 0, 0.0))
        suggestions.append(
            TopicSuggestion(
                topic_id=t.topic_id,
                display_name=t.display_name,
                relationship="core",
                career_count=cc,
                recent_count=rc,
                shift=round(sh, 3),
                subfield=t.subfield,
                field=t.field,
                domain=t.domain,
            )
        )

    rising = sorted(
        (tid for tid in shifts if tid not in core_ids and shifts[tid][1] >= 2),
        key=lambda tid: (shifts[tid][2], shifts[tid][1]),
        reverse=True,
    )
    for tid in rising[:5]:
        cc, rc, sh = shifts[tid]
        if sh <= 0:
            continue
        suggestions.append(
            TopicSuggestion(
                topic_id=tid,
                display_name=names.get(tid, tid),
                relationship="recent_shift",
                career_count=cc,
                recent_count=rc,
                shift=round(sh, 3),
            )
        )

    seen = {s.topic_id for s in suggestions}
    for t in co_occurring:
        if t.topic_id in seen:
            continue
        cc, rc, sh = shifts.get(t.topic_id, (0, 0, 0.0))
        suggestions.append(
            TopicSuggestion(
                topic_id=t.topic_id,
                display_name=t.display_name,
                relationship="adjacent",
                career_count=cc,
                recent_count=rc,
                co_occurrence=t.count,
                shift=round(sh, 3),
                subfield=t.subfield,
                field=t.field,
                domain=t.domain,
            )
        )
        if len(suggestions) >= limit + 5:
            break

    return suggestions[:limit]


def _item_text_and_abstract(item: Any) -> tuple[str, str]:
    if isinstance(item, PaperMatch):
        return item.title, item.finding if item.finding != item.title else ""
    if isinstance(item, Mapping):
        title = str(item.get("title") or "").strip()
        abstract = str(item.get("abstract") or "").strip()
        if not abstract and "abstract_inverted_index" in item:
            abstract = reconstruct_abstract(item.get("abstract_inverted_index"))
        return title, abstract
    title = str(getattr(item, "title", "") or "").strip()
    abstract = str(getattr(item, "abstract", "") or "").strip()
    return title, abstract


def rrf_order(
    question: str,
    papers: Sequence[Any],
    *,
    profile_terms: tuple[str, ...] = (),
    top_n: int | None = None,
) -> list[Any]:
    """Reciprocal Rank Fusion over the existing channel order and lexical
    overlap rank (`1 / (k + rank)` with `RRF_K = 60`), with an abstract bonus
    so metadata-only stubs lose ties."""
    if not papers:
        return []
    items = list(papers)
    overlaps = [
        _topic_overlap_score(
            question,
            *_item_text_and_abstract(p),
            profile_terms=profile_terms,
        )
        for p in items
    ]
    has_abs = [1 if _item_text_and_abstract(p)[1] else 0 for p in items]
    lex_sorted = sorted(
        range(len(items)),
        key=lambda idx: (overlaps[idx], has_abs[idx], -idx),
        reverse=True,
    )
    lex_rank = {orig_idx: r for r, orig_idx in enumerate(lex_sorted)}

    def _score(ch_i: int) -> tuple[float, int, int, int]:
        rrf = round(1.0 / (RRF_K + ch_i) + 1.0 / (RRF_K + lex_rank[ch_i]), 12)
        return (rrf, has_abs[ch_i], overlaps[ch_i], -ch_i)

    ranked_indices = sorted(range(len(items)), key=_score, reverse=True)
    ranked = [items[i] for i in ranked_indices]
    return ranked[:top_n] if top_n else ranked


_POST_COMMA_SUFFIXES = frozenset({
    "phd", "ph.d", "md", "m.d", "jr", "sr", "ii", "iii", "iv",
    "prof", "professor", "dr", "ing", "habil", "frs", "obe", "cbe", "kbe",
})
_INVERTED_NAME_RE = re.compile(
    r"^([^\d,;:()]{2,50}),\s*([^\d,;:()]{1,50})$"
)


def normalize_inverted_person_name(entity: str) -> str:
    """Convert bibliography-inverted `'Surname, Initials/Given'` (e.g.
    `'Broeders, D.W.J.'` or `'Broeders, Dennis'`) into natural prose order
    (`'D.W.J. Broeders'` / `'Dennis Broeders'`) while leaving post-nominal
    credentials (`'Jane Doe, PhD'`) untouched."""
    text = " ".join(entity.strip().split())
    m = _INVERTED_NAME_RE.match(text)
    if not m:
        return text
    left, right = m.group(1).strip(), m.group(2).strip()
    right_tokens = [t.casefold().rstrip(".") for t in right.split() if t.strip(".")]
    if not right_tokens or any(t in _POST_COMMA_SUFFIXES for t in right_tokens):
        return text
    if not left[:1].isupper() or not right[:1].isupper():
        return text
    return f"{right} {left}"


def strip_academic_titles(entity: str) -> str:
    text = normalize_inverted_person_name(entity.strip())
    while True:
        stripped = _TITLE_PREFIX.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    return normalize_inverted_person_name(text)


def _initial_prefixes(raw_token: str, variants: set[str]) -> set[str]:
    prefixes = {v[0] for v in variants if v}
    for v in variants:
        if len(v) <= 2:
            prefixes.add(v)
    return prefixes


def _candidate_splits(tokens: list[str]) -> list[tuple[str, list[str], bool]]:
    """Return (surname_token, given_tokens, is_surname_first) candidates for `tokens`."""
    if not tokens:
        return []
    splits: list[tuple[str, list[str], bool]] = [(tokens[-1], tokens[:-1], False)]
    if len(tokens) >= 3:
        splits.append((tokens[-2], tokens[:-2], False))
    if len(tokens) >= 2:
        splits.append((tokens[0], tokens[1:], True))
    return splits


def _splits_match(
    surname_raw: str,
    given: list[str],
    author_surname_raw: str,
    author_given: list[str],
) -> bool:
    surname_vars = name_token_variants(surname_raw)
    if not surname_vars or all(len(v) < 2 for v in surname_vars):
        return False
    have_surname_vars = name_token_variants(author_surname_raw)
    if not (surname_vars & have_surname_vars):
        return False
    if not given:
        return True
    if not author_given:
        return False
    want_first_raw = given[0]
    want_first_vars = name_token_variants(want_first_raw)
    have_first_raw = author_given[0]
    have_first_vars = name_token_variants(have_first_raw)
    if not want_first_vars or not have_first_vars:
        return False
    if want_first_vars & have_first_vars:
        return True
    if len(want_first_raw) == 1:
        want_prefixes = _initial_prefixes(want_first_raw, want_first_vars)
        if any(hv.startswith(p) for hv in have_first_vars for p in want_prefixes if p):
            return True
    if len(have_first_raw) == 1:
        have_prefixes = _initial_prefixes(have_first_raw, have_first_vars)
        if any(wv.startswith(p) for wv in want_first_vars for p in have_prefixes if p):
            return True
    return False


def person_matches_author(entity: str, author_names: tuple[str, ...]) -> bool:
    """Whether `entity` (e.g. 'Prof. Dr. M. Kaya', 'Prof. Dr. Orxan Əliyev',
    'Prof. Dr. Jürgen Müller', or 'Проф. И. Петров') matches one of an OpenAlex
    author's display names across scripts, transliterations, compound surnames,
    and surname-first order."""
    clean_entity = _NON_ALPHA.sub(" ", strip_academic_titles(entity)).split()
    if not clean_entity:
        return False
    entity_splits = _candidate_splits(clean_entity)
    for raw_name in author_names:
        tokens = _NON_ALPHA.sub(" ", raw_name).split()
        if not tokens:
            continue
        author_splits = _candidate_splits(tokens)
        for e_sur, e_giv, e_sf in entity_splits:
            for a_sur, a_giv, a_sf in author_splits:
                if e_sf and a_sf:
                    continue
                if (e_sf or a_sf) and (not e_giv or not a_giv):
                    continue
                if _splits_match(e_sur, e_giv, a_sur, a_giv):
                    return True
    return False


def reconstruct_abstract(inverted_index: object) -> str:
    """Rebuild plain text from OpenAlex's `abstract_inverted_index`."""
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, indices in inverted_index.items():
        if not isinstance(word, str) or not isinstance(indices, list):
            continue
        for pos in indices:
            if isinstance(pos, int) and 0 <= pos < 5_000:
                positions[pos] = word
    if not positions:
        return ""
    return " ".join(positions[idx] for idx in sorted(positions)).strip()


def extract_work_phrase(abstract: str, title: str) -> str:
    """Extract a verbatim finding or method sentence from `abstract` (spec
    2026-09-28 §3.4), preferring sentences with explicit result cues and
    falling back to the last/second sentence or `title`."""
    if abstract:
        sentences = [s.strip() for s in page_sentences([abstract]) if len(s.strip()) >= 25]
        if sentences:
            for sent in sentences:
                if _WORK_PHRASE_CUE_RE.search(sent):
                    return sent[:240]
            pick = sentences[-1] if len(sentences) > 1 else sentences[0]
            return pick[:240]
    return title[:240]


def extract_method_or_question(abstract: str, finding: str = "") -> str:
    """Extract a complementary problem-bottleneck, methodology, or open-question
    sentence from `abstract` (distinct from `finding`) so the motivation letter
    can connect to the lab's live research question and method."""
    if not abstract:
        return ""
    sentences = [s.strip() for s in page_sentences([abstract]) if len(s.strip()) >= 25]
    for sent in sentences:
        if sent[:240] == finding:
            continue
        if _METHOD_OR_QUESTION_CUE_RE.search(sent):
            return sent[:240]
    return ""


def _extract_work_metadata_question(work: Mapping[str, object], finding: str = "") -> str:
    """When a monograph, book chapter, or closed-abstract publication has no plain-text
    abstract, synthesize a factual scope descriptor from OpenAlex's `keywords` and
    `topics`/`primary_topic` metadata (common in Humanities, Law, and Social Sciences)."""
    terms: list[str] = []
    seen: set[str] = set()
    finding_low = (finding or "").casefold()

    def _add(val: object) -> None:
        text = str(val or "").strip()
        low = text.casefold()
        if len(text) >= 4 and low not in seen and low != finding_low:
            seen.add(low)
            terms.append(text)

    keywords = work.get("keywords")
    if isinstance(keywords, list):
        for kw in keywords[:4]:
            if isinstance(kw, Mapping):
                _add(kw.get("display_name"))
    pt = work.get("primary_topic")
    if isinstance(pt, Mapping):
        _add(pt.get("display_name"))
        sub = pt.get("subfield")
        if isinstance(sub, Mapping):
            _add(sub.get("display_name"))
    topics = work.get("topics")
    if isinstance(topics, list):
        for tp in topics[:3]:
            if isinstance(tp, Mapping):
                _add(tp.get("display_name"))
    if not terms:
        return ""
    return f"Addresses {', '.join(terms[:3])}."[:240]


def _author_role(authorship: Mapping[str, object], total_authors: int) -> str:
    """Whether the matched author is a primary/senior author ('lead') or a
    middle co-author ('group') (spec 2026-10-14 §6.1 / discovery Q1a)."""
    if total_authors <= 1:
        return "lead"
    if bool(authorship.get("is_corresponding")):
        return "lead"
    pos = str(authorship.get("author_position") or "").strip().lower()
    if pos == "middle":
        return "group"
    return "lead"


def _is_senior_author(authorship: Mapping[str, object], total_authors: int) -> bool:
    """Whether the authorship represents supervisory/PI seniority ('last',
    corresponding, or sole author) rather than a trainee first-author role on a
    multi-author work."""
    if total_authors <= 1:
        return True
    if bool(authorship.get("is_corresponding")):
        return True
    pos = str(authorship.get("author_position") or "").strip().lower()
    return pos == "last"


def _cached_fetch_json_api(
    url: str, *, params: Mapping[str, object], headers: Mapping[str, str]
) -> dict[str, object]:
    """7-day cache for OpenAlex and Crossref responses (zero student PII in key
    or payload) so repeated lookups across people on the same page, anchors or
    students hit Redis/Valkey instead of making redundant external HTTP calls."""
    payload = json.dumps({"u": url, "p": dict(params)}, sort_keys=True, default=str)
    cache_key = f"research-fit:paper-api:{hashlib.sha256(payload.encode()).hexdigest()}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return cached
    data = fetch_json_api(url, params=params, headers=headers)
    if isinstance(data, dict):
        cache.set(cache_key, data, timeout=PAPER_CACHE_TTL_SECONDS)
    return data


def _crossref_abstract(
    doi_url: str, *, get_json: Callable[..., dict[str, object]]
) -> str:
    """Recover plain-text abstract from Crossref when OpenAlex's inverted index
    is empty (common on Elsevier/IEEE DOIs). Zero student data leaves the machine."""
    if not doi_url.startswith("https://doi.org/10."):
        return ""
    doi = doi_url.removeprefix("https://doi.org/").strip()
    if not doi:
        return ""
    try:
        data = get_json(f"{CROSSREF_WORKS_URL}{doi}", params={}, headers={})
    except Exception as exc:
        logger.warning(
            "crossref abstract lookup degraded for %s (%s): %s",
            doi,
            type(exc).__name__,
            exc,
        )
        return ""
    msg = data.get("message") if isinstance(data, dict) else None
    if not isinstance(msg, dict):
        return ""
    raw = str(msg.get("abstract") or "").strip()
    if not raw:
        return ""
    return " ".join(_JATS_TAG_RE.sub(" ", raw).split())


def _europepmc_abstract(
    doi_url: str, *, get_json: Callable[..., dict[str, object]]
) -> str:
    """Recover plain-text abstract from Europe PMC REST search when both OpenAlex
    and Crossref lack an abstract (common for biomedical, life-science, and
    closed-publisher DOIs indexed by PubMed/Europe PMC)."""
    if not doi_url.startswith("https://doi.org/10."):
        return ""
    doi = doi_url.removeprefix("https://doi.org/").strip()
    if not doi:
        return ""
    params = {
        "query": f'DOI:"{doi}"',
        "format": "json",
        "resultType": "core",
        "pageSize": "1",
    }
    try:
        data = get_json(EUROPEPMC_SEARCH_URL, params=params, headers={})
    except Exception as exc:
        logger.warning(
            "europepmc abstract lookup degraded for %s (%s): %s",
            doi,
            type(exc).__name__,
            exc,
        )
        return ""
    result_list = data.get("resultList") if isinstance(data, Mapping) else None
    results = result_list.get("result") if isinstance(result_list, Mapping) else None
    if not isinstance(results, list) or not results:
        return ""
    first = results[0]
    if not isinstance(first, Mapping):
        return ""
    raw = str(first.get("abstractText") or "").strip()
    if not raw:
        return ""
    return " ".join(_JATS_TAG_RE.sub(" ", raw).split())


def _extract_arxiv_summary_from_xml(xml_text: str) -> str:
    """Extract the Atom `<summary>` text from an arXiv API response."""
    if not xml_text.strip():
        return ""
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        logger.warning("arxiv atom xml parse degraded (%s): %s", type(exc).__name__, exc)
        return ""
    entry = root.find(f"{_ATOM_NS}entry")
    if entry is None:
        return ""
    summary = str(entry.findtext(f"{_ATOM_NS}summary") or "").strip()
    if not summary:
        return ""
    return " ".join(_JATS_TAG_RE.sub(" ", summary).split())


def _arxiv_abstract(
    url: str,
    *,
    get_json: Callable[..., dict[str, object]] | None = None,
) -> str:
    """Recover plain-text abstract from the arXiv Atom API for `10.48550/arXiv.*`
    DOIs or `https://arxiv.org/abs/*` URLs when OpenAlex's inverted index is empty."""
    lower = url.casefold()
    arxiv_id = ""
    if lower.startswith(_ARXIV_DOI_URL_PREFIX):
        arxiv_id = url[len(_ARXIV_DOI_URL_PREFIX) :].strip()
    elif lower.startswith("https://arxiv.org/abs/"):
        arxiv_id = url[len("https://arxiv.org/abs/") :].strip()
    if not arxiv_id:
        return ""
    if get_json is not None and get_json is not _cached_fetch_json_api:
        try:
            data = get_json(
                ARXIV_API_URL,
                params={"id_list": arxiv_id, "max_results": "1"},
                headers={},
            )
        except Exception as exc:
            logger.warning(
                "arxiv abstract lookup via loader degraded for %s (%s): %s",
                arxiv_id,
                type(exc).__name__,
                exc,
            )
            return ""
        if isinstance(data, Mapping):
            if raw_summary := str(data.get("summary") or "").strip():
                return " ".join(_JATS_TAG_RE.sub(" ", raw_summary).split())
            if raw_xml := str(data.get("xml") or "").strip():
                return _extract_arxiv_summary_from_xml(raw_xml)
        return ""
    cache_key = (
        f"research-fit:arxiv-abs:{hashlib.sha256(arxiv_id.casefold().encode()).hexdigest()}"
    )
    cached = cache.get(cache_key)
    if isinstance(cached, str):
        return cached
    query_url = f"{ARXIV_API_URL}?id_list={quote(arxiv_id, safe='')}&max_results=1"
    try:
        status, body_bytes, _ = Urllib3Transport().get_bytes(query_url, max_bytes=262_144)
    except Exception as exc:
        logger.warning(
            "arxiv abstract lookup degraded for %s (%s): %s",
            arxiv_id,
            type(exc).__name__,
            exc,
        )
        return ""
    if status != 200 or not body_bytes:
        return ""
    xml_text = body_bytes.decode("utf-8", errors="replace")
    summary = _extract_arxiv_summary_from_xml(xml_text)
    if summary:
        cache.set(cache_key, summary, timeout=PAPER_CACHE_TTL_SECONDS)
    return summary


def _recover_missing_abstract(
    url: str, *, get_json: Callable[..., dict[str, object]]
) -> str:
    """Multi-source abstract waterfall when OpenAlex `abstract_inverted_index`
    is empty: arXiv Atom API (for `10.48550/arXiv.*` / `arxiv.org/abs/*`), then
    Crossref REST API, then Europe PMC REST API."""
    lower = url.casefold()
    if lower.startswith(_ARXIV_DOI_URL_PREFIX) or lower.startswith("https://arxiv.org/abs/"):
        arxiv_abs = _arxiv_abstract(url, get_json=get_json)
        if arxiv_abs:
            return arxiv_abs
    if url.startswith("https://doi.org/10."):
        crossref_abs = _crossref_abstract(url, get_json=get_json)
        if crossref_abs:
            return crossref_abs
        return _europepmc_abstract(url, get_json=get_json)
    return ""


def _topic_overlap_score(
    topic: str,
    title: str,
    abstract: str,
    profile_terms: tuple[str, ...] = (),
    primary_topic: Mapping[str, object] | None = None,
) -> int:
    topic_words = {
        w for w in _NON_ALPHA.sub(" ", topic).casefold().split() if len(w) >= 4
    }
    profile_words = {
        w.casefold() for w in profile_terms if len(w) >= 4
    } - topic_words
    if not topic_words and not profile_words:
        return 0
    extra_parts: list[str] = []
    if isinstance(primary_topic, Mapping):
        for key in ("display_name",):
            if val := str(primary_topic.get(key) or "").strip():
                extra_parts.append(val)
        for level in ("subfield", "field", "domain"):
            sub = primary_topic.get(level)
            if isinstance(sub, Mapping) and (val := str(sub.get("display_name") or "").strip()):
                extra_parts.append(val)
    haystack_text = " ".join([title, abstract, *extra_parts])
    haystack_set = set(_NON_ALPHA.sub(" ", haystack_text).casefold().split())
    return (
        sum(2 for w in topic_words if w in haystack_set)
        + sum(1 for w in profile_words if w in haystack_set)
    )


def _work_topic_id(work: Mapping[str, object]) -> tuple[str, str]:
    pt = work.get("primary_topic")
    if isinstance(pt, Mapping):
        tid = str(pt.get("id") or "").strip()
        name = str(pt.get("display_name") or tid).strip()
        if tid:
            return tid, name
    topics = work.get("topics")
    if isinstance(topics, list) and topics:
        first = topics[0]
        if isinstance(first, Mapping):
            tid = str(first.get("id") or "").strip()
            name = str(first.get("display_name") or tid).strip()
            if tid:
                return tid, name
    return "", ""


def _compute_work_topic_shifts(
    works: Sequence[object], year_now: int
) -> dict[str, float]:
    """Compute per-topic `recent_share - career_share` across a set of OpenAlex works."""
    career_tally: dict[str, tuple[str, int]] = {}
    recent_tally: dict[str, tuple[str, int]] = {}
    recent_cutoff = year_now - RECENT_YEARS + 1
    for work in works:
        if not isinstance(work, Mapping) or work.get("is_retracted"):
            continue
        tid, name = _work_topic_id(work)
        if not tid:
            continue
        year_raw = work.get("publication_year")
        year = int(year_raw) if isinstance(year_raw, int) else 0
        prev_name, prev_c = career_tally.get(tid, (name, 0))
        career_tally[tid] = (prev_name, prev_c + 1)
        if year >= recent_cutoff:
            r_name, prev_r = recent_tally.get(tid, (name, 0))
            recent_tally[tid] = (r_name, prev_r + 1)
    if not career_tally:
        return {}
    career_list = [
        TopicCount(topic_id=tid, display_name=nm, count=cnt)
        for tid, (nm, cnt) in career_tally.items()
    ]
    recent_list = [
        TopicCount(topic_id=tid, display_name=nm, count=cnt)
        for tid, (nm, cnt) in recent_tally.items()
    ]
    shifts = recency_shift(career_list, recent_list)
    return {tid: sh for tid, (_, _, sh) in shifts.items()}


def _author_matches_institution(
    authorship: Mapping[str, object],
    institution_name: str,
    domains: tuple[str, ...],
    ror_ids: tuple[str, ...] = (),
) -> bool:
    inst_norm = _NON_ALPHA.sub(" ", institution_name).casefold().strip()
    domain_roots = tuple(d.split(".")[0].casefold() for d in domains if d)
    ror_norm = {r.rstrip("/").rsplit("/", 1)[-1].casefold() for r in ror_ids if r}
    institutions = authorship.get("institutions")
    if isinstance(institutions, list):
        for inst in institutions:
            if not isinstance(inst, dict):
                continue
            inst_ror = str(inst.get("ror") or "").rstrip("/").rsplit("/", 1)[-1].casefold()
            if inst_ror and inst_ror in ror_norm:
                return True
            display = _NON_ALPHA.sub(" ", str(inst.get("display_name") or "")).casefold().strip()
            if inst_norm and (inst_norm in display or display in inst_norm):
                return True
            if any(root and len(root) >= 4 and root in display.split() for root in domain_roots):
                return True
    raw_affs = authorship.get("raw_affiliation_strings")
    if isinstance(raw_affs, list):
        for raw in raw_affs:
            text = _NON_ALPHA.sub(" ", str(raw or "")).casefold()
            if inst_norm and inst_norm in text:
                return True
            if any(root and len(root) >= 4 and root in text for root in domain_roots):
                return True
    return not inst_norm and not ror_norm


def resolve_openalex_author_id(
    *,
    entity: str,
    institution_name: str = "",
    domains: tuple[str, ...] = (),
    ror_ids: tuple[str, ...] = (),
    api_key: str | None = None,
    get_json: Callable[..., dict[str, object]] | None = None,
) -> str | None:
    """Resolve `entity` (OpenAlex ID, ORCID, or faculty name at `institution_name`)
    to an OpenAlex Author ID ('A...')."""
    key = api_key if api_key is not None else settings.OPENALEX_API_KEY
    if not key:
        return None
    loader = get_json or _cached_fetch_json_api
    kind, value = classify_identifier(strip_academic_titles(entity))
    if not value:
        return None
    if kind == "openalex":
        return value
    headers = {"api-key": key}
    if kind == "orcid":
        try:
            data = loader(
                f"{OPENALEX_AUTHORS_URL}/https://orcid.org/{value}",
                params={},
                headers=headers,
            )
        except Exception as exc:
            logger.warning("openalex orcid author lookup degraded for '%s': %s", value, exc)
            return None
        raw_id = str(data.get("id") or "").strip() if isinstance(data, Mapping) else ""
        return raw_id.rsplit("/", 1)[-1] if raw_id else None

    params: dict[str, object] = {"search": value, "per-page": "10"}
    try:
        data = loader(OPENALEX_AUTHORS_URL, params=params, headers=headers)
    except Exception as exc:
        logger.warning("openalex author search degraded for '%s': %s", value, exc)
        return None
    results = data.get("results") if isinstance(data, Mapping) else None
    if not isinstance(results, list):
        return None
    for cand in results:
        if not isinstance(cand, Mapping):
            continue
        names: list[str] = []
        if disp := str(cand.get("display_name") or "").strip():
            names.append(disp)
        alts = cand.get("display_name_alternatives")
        if isinstance(alts, list):
            names.extend(str(a).strip() for a in alts if str(a).strip())
        if not person_matches_author(entity, tuple(names)):
            continue
        insts: list[dict[str, object]] = []
        for k in ("last_known_institutions", "affiliations"):
            raw_list = cand.get(k)
            if isinstance(raw_list, list):
                for item in raw_list:
                    if isinstance(item, dict):
                        inst_obj = item.get("institution") if "institution" in item else item
                        if isinstance(inst_obj, dict):
                            insts.append(inst_obj)
        synth_authorship: dict[str, object] = {"institutions": insts}
        if _author_matches_institution(
            synth_authorship, institution_name, domains, ror_ids=ror_ids
        ):
            raw_id = str(cand.get("id") or "").strip()
            if raw_id:
                return raw_id.rsplit("/", 1)[-1]
    return None


def _query_openalex_works(
    *,
    topic: str,
    institution_name: str,
    current_year: int | None,
    api_key: str | None,
    get_json: Callable[..., dict[str, object]],
) -> tuple[list[object], int, int] | None:
    key = api_key if api_key is not None else settings.OPENALEX_API_KEY
    if not key:
        return None
    year_now = current_year or datetime.now(tz=UTC).year
    min_year = year_now - _MAX_PAPER_AGE_YEARS
    filters = ["is_retracted:false", f"publication_year:{min_year}-{year_now}"]
    if clean_inst := _NON_ALPHA.sub(" ", institution_name).strip():
        filters.append(f"raw_affiliation_strings.search:{clean_inst}")
    params: dict[str, object] = {
        "search.title_and_abstract": topic,
        "filter": ",".join(filters),
        "per-page": "15",
        "select": "id,title,publication_year,doi,authorships,abstract_inverted_index,is_retracted",
    }
    try:
        data = get_json(OPENALEX_WORKS_URL, params=params, headers={"api-key": key})
    except Exception as exc:
        logger.warning(
            "openalex works lookup degraded for '%s' (%s): %s",
            institution_name,
            type(exc).__name__,
            exc,
        )
        return None
    results = data.get("results") if isinstance(data, dict) else None
    return (results, year_now, min_year) if isinstance(results, list) else None


def _query_openalex_author_works(
    *,
    author_id: str,
    current_year: int | None,
    api_key: str | None,
    get_json: Callable[..., dict[str, object]],
) -> list[object]:
    key = api_key if api_key is not None else settings.OPENALEX_API_KEY
    if not key or not author_id:
        return []
    year_now = current_year or datetime.now(tz=UTC).year
    min_year = year_now - _MAX_PAPER_AGE_YEARS
    params: dict[str, object] = {
        "filter": (
            f"authorships.author.id:{author_id},"
            f"is_retracted:false,publication_year:{min_year}-{year_now}"
        ),
        "per-page": "25",
        "select": (
            "id,title,publication_year,doi,authorships,"
            "abstract_inverted_index,is_retracted,primary_topic,topics"
        ),
    }
    try:
        data = get_json(OPENALEX_WORKS_URL, params=params, headers={"api-key": key})
    except Exception as exc:
        logger.warning("openalex author works lookup degraded for '%s': %s", author_id, exc)
        return []
    results = data.get("results") if isinstance(data, Mapping) else None
    return results if isinstance(results, list) else []


def _score_person_works(
    results: Sequence[object],
    *,
    entity: str,
    topic: str,
    institution_name: str,
    domains: tuple[str, ...],
    profile_terms: tuple[str, ...],
    ror_ids: tuple[str, ...],
    year_now: int,
    min_year: int,
    loader: Callable[..., dict[str, object]],
) -> list[tuple[tuple[int, int, int, int, int, float, int], PaperMatch]]:
    topic_shifts = _compute_work_topic_shifts(results, year_now)
    raw_items: list[tuple[int, int, int, int, int, int, PaperMatch]] = []
    for work in results:
        if not isinstance(work, dict) or work.get("is_retracted"):
            continue
        title = str(work.get("title") or "").strip()
        year_raw = work.get("publication_year")
        year = int(year_raw) if isinstance(year_raw, int) else 0
        if not title or year < min_year:
            continue
        authorships = work.get("authorships")
        if not isinstance(authorships, list):
            continue
        matched_role: str | None = None
        for authorship in authorships:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author")
            if not isinstance(author, dict):
                continue
            names: list[str] = []
            if disp := str(author.get("display_name") or "").strip():
                names.append(disp)
            alts = author.get("display_name_alternatives")
            if isinstance(alts, list):
                names.extend(str(a).strip() for a in alts if str(a).strip())
            if person_matches_author(entity, tuple(names)) and _author_matches_institution(
                authorship, institution_name, domains, ror_ids=ror_ids
            ):
                matched_role = _author_role(authorship, len(authorships))
                break
        if matched_role is None:
            continue
        url = str(work.get("doi") or work.get("id") or "").strip()
        if not url.startswith("https://"):
            continue
        abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
        if not abstract:
            abstract = _recover_missing_abstract(url, get_json=loader)
        finding = extract_work_phrase(abstract, title)
        method_or_question = extract_method_or_question(
            abstract, finding
        ) or _extract_work_metadata_question(work, finding)
        pt = work.get("primary_topic")
        overlap = _topic_overlap_score(
            topic,
            title,
            abstract,
            profile_terms=profile_terms,
            primary_topic=pt if isinstance(pt, Mapping) else None,
        )
        tid, topic_name = _work_topic_id(work)
        shift = topic_shifts.get(tid, 0.0) if tid else 0.0
        drift_bonus = 1 if shift > 0.0 else (-1 if shift < -0.05 else 0)
        active_topic = topic_name if shift > 0.0 else ""
        is_lead = 1 if matched_role == "lead" else 0
        has_abs = 1 if bool(abstract) else 0
        is_recent = 1 if year >= year_now - _RECENT_BONUS_YEARS else 0
        raw_items.append(
            (
                is_lead,
                has_abs,
                overlap,
                drift_bonus,
                is_recent,
                year,
                PaperMatch(
                    title=title[:300],
                    year=year,
                    url=url,
                    finding=finding,
                    author_role=matched_role,
                    method_or_question=method_or_question,
                    active_topic=active_topic,
                ),
            )
        )
    if not raw_items:
        return []
    lex_order = sorted(
        range(len(raw_items)),
        key=lambda i: (raw_items[i][2], raw_items[i][3], raw_items[i][5]),
        reverse=True,
    )
    lex_rank = {orig_i: r for r, orig_i in enumerate(lex_order)}
    rec_order = sorted(
        range(len(raw_items)),
        key=lambda i: (raw_items[i][3], raw_items[i][4], raw_items[i][5], -i),
        reverse=True,
    )
    rec_rank = {orig_i: r for r, orig_i in enumerate(rec_order)}

    candidates: list[tuple[tuple[int, int, int, int, int, float, int], PaperMatch]] = []
    for idx, (is_lead, has_abs, overlap, drift_bonus, is_recent, year, pm) in enumerate(raw_items):
        rrf = 1.0 / (RRF_K + lex_rank[idx]) + 1.0 / (RRF_K + rec_rank[idx])
        score = (is_lead, has_abs, overlap, drift_bonus, is_recent, round(rrf, 6), year)
        candidates.append((score, pm))
    return candidates


def lookup_person_paper(
    *,
    entity: str,
    topic: str,
    institution_name: str,
    domains: tuple[str, ...] = (),
    profile_terms: tuple[str, ...] = (),
    ror_ids: tuple[str, ...] = (),
    current_year: int | None = None,
    api_key: str | None = None,
    get_json: Callable[..., dict[str, object]] | None = None,
) -> PaperMatch | None:
    """Return one recent non-retracted paper by `entity` at `institution_name`
    on `topic`, ranked by relevance first (lead role, abstract presence, topic
    and student-profile vocabulary overlap), topic-drift recency (`recency_shift`),
    and Reciprocal Rank Fusion (`rrf_order`) (spec 2026-10-14 §6.2)."""
    if not strip_academic_titles(entity) or not topic:
        return None
    loader = get_json or _cached_fetch_json_api
    queried = _query_openalex_works(
        topic=topic,
        institution_name=institution_name,
        current_year=current_year,
        api_key=api_key,
        get_json=loader,
    )
    if queried is None:
        return None
    results, year_now, min_year = queried
    candidates = _score_person_works(
        results,
        entity=entity,
        topic=topic,
        institution_name=institution_name,
        domains=domains,
        profile_terms=profile_terms,
        ror_ids=ror_ids,
        year_now=year_now,
        min_year=min_year,
        loader=loader,
    )
    has_topical_lead = any(score[0] >= 1 and score[2] > 0 for score, _ in candidates)
    if not candidates or not has_topical_lead:
        author_id = resolve_openalex_author_id(
            entity=entity,
            institution_name=institution_name,
            domains=domains,
            ror_ids=ror_ids,
            api_key=api_key,
            get_json=loader,
        )
        if author_id:
            author_works = _query_openalex_author_works(
                author_id=author_id,
                current_year=current_year,
                api_key=api_key,
                get_json=loader,
            )
            if author_works:
                merged_works: list[object] = []
                seen_work_keys: set[str] = set()
                for work in (*results, *author_works):
                    if isinstance(work, Mapping):
                        wkey = (
                            str(work.get("id") or "").strip()
                            or str(work.get("doi") or "").strip()
                        )
                        if wkey and wkey in seen_work_keys:
                            continue
                        if wkey:
                            seen_work_keys.add(wkey)
                    merged_works.append(work)
                candidates = _score_person_works(
                    merged_works,
                    entity=entity,
                    topic=topic,
                    institution_name=institution_name,
                    domains=domains,
                    profile_terms=profile_terms,
                    ror_ids=ror_ids,
                    year_now=year_now,
                    min_year=min_year,
                    loader=loader,
                )
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def lookup_group_paper(
    *,
    group_entity: str,
    topic: str,
    institution_name: str,
    domains: tuple[str, ...] = (),
    profile_terms: tuple[str, ...] = (),
    ror_ids: tuple[str, ...] = (),
    current_year: int | None = None,
    api_key: str | None = None,
    get_json: Callable[..., dict[str, object]] | None = None,
) -> PaperMatch | None:
    """Return one recent non-retracted paper from `group_entity` (a research
    group, chair or laboratory) at `institution_name` on `topic` (Topology T3:
    lab page without a single named PI)."""
    group_tokens = {
        w
        for w in _NON_ALPHA.sub(" ", group_entity).casefold().split()
        if len(w) >= 4 and w not in _GROUP_STOP_WORDS
    }
    if not group_tokens or not topic:
        return None
    loader = get_json or _cached_fetch_json_api
    queried = _query_openalex_works(
        topic=topic,
        institution_name=institution_name,
        current_year=current_year,
        api_key=api_key,
        get_json=loader,
    )
    if queried is None:
        return None
    results, year_now, min_year = queried
    candidates: list[tuple[tuple[int, int, int, int, int], PaperMatch]] = []
    for work in results:
        if not isinstance(work, dict) or work.get("is_retracted"):
            continue
        title = str(work.get("title") or "").strip()
        year_raw = work.get("publication_year")
        year = int(year_raw) if isinstance(year_raw, int) else 0
        if not title or year < min_year:
            continue
        url = str(work.get("doi") or work.get("id") or "").strip()
        if not url.startswith("https://"):
            continue
        authorships = work.get("authorships")
        if not isinstance(authorships, list):
            continue
        inst_matched = False
        aff_tokens: set[str] = set()
        for authorship in authorships:
            if not isinstance(authorship, dict):
                continue
            if _author_matches_institution(authorship, institution_name, domains, ror_ids=ror_ids):
                inst_matched = True
            raw_affs = authorship.get("raw_affiliation_strings")
            if isinstance(raw_affs, list):
                for raw in raw_affs:
                    aff_tokens.update(_NON_ALPHA.sub(" ", str(raw or "")).casefold().split())
        if not inst_matched:
            continue
        abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
        if not abstract:
            abstract = _recover_missing_abstract(url, get_json=loader)
        text_tokens = set(_NON_ALPHA.sub(" ", f"{title} {abstract}").casefold().split())
        aff_group_hits = len(group_tokens & aff_tokens)
        text_group_hits = len(group_tokens & text_tokens)
        if aff_group_hits == 0 and text_group_hits == 0:
            continue
        finding = extract_work_phrase(abstract, title)
        method_or_question = extract_method_or_question(
            abstract, finding
        ) or _extract_work_metadata_question(work, finding)
        score = (
            1 if aff_group_hits > 0 else 0,
            1 if bool(abstract) else 0,
            _topic_overlap_score(topic, title, abstract, profile_terms=profile_terms)
            + aff_group_hits,
            1 if year >= year_now - _RECENT_BONUS_YEARS else 0,
            year,
        )
        candidates.append(
            (
                score,
                PaperMatch(
                    title=title[:300],
                    year=year,
                    url=url,
                    finding=finding,
                    author_role="group",
                    method_or_question=method_or_question,
                ),
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def discover_literature_person_on_page(
    sentences: tuple[str, ...],
    *,
    topic: str,
    institution_name: str,
    domains: tuple[str, ...] = (),
    profile_terms: tuple[str, ...] = (),
    ror_ids: tuple[str, ...] = (),
    current_year: int | None = None,
    api_key: str | None = None,
    get_json: Callable[..., dict[str, object]] | None = None,
) -> tuple[ClassifiedSentence, PaperMatch] | None:
    """Literature-first discovery confirmed on an already-fetched university
    page (discovery Q1a): when a page lists faculty names without topic
    descriptions in the same sentence, find a recent non-retracted paper on
    `topic` at `institution_name` whose author's name appears verbatim on
    `sentences` (and is not marked emeritus/visiting/on leave or a trainee)."""
    if not sentences or not topic:
        return None
    loader = get_json or _cached_fetch_json_api
    queried = _query_openalex_works(
        topic=topic,
        institution_name=institution_name,
        current_year=current_year,
        api_key=api_key,
        get_json=loader,
    )
    if queried is None:
        return None
    results, year_now, min_year = queried
    topic_shifts = _compute_work_topic_shifts(results, year_now)

    author_work_counts: dict[str, int] = {}
    for work in results:
        if not isinstance(work, dict) or work.get("is_retracted"):
            continue
        year_raw = work.get("publication_year")
        year = int(year_raw) if isinstance(year_raw, int) else 0
        if year < min_year:
            continue
        authorships = work.get("authorships")
        if not isinstance(authorships, list):
            continue
        for authorship in authorships:
            if not isinstance(authorship, dict):
                continue
            author = authorship.get("author")
            if isinstance(author, dict) and (disp := str(author.get("display_name") or "").strip()):
                key = disp.casefold()
                author_work_counts[key] = author_work_counts.get(key, 0) + 1

    candidates: list[
        tuple[tuple[int, int, int, int, int, int], ClassifiedSentence, PaperMatch]
    ] = []
    for work in results:
        if not isinstance(work, dict) or work.get("is_retracted"):
            continue
        title = str(work.get("title") or "").strip()
        year_raw = work.get("publication_year")
        year = int(year_raw) if isinstance(year_raw, int) else 0
        if not title or year < min_year:
            continue
        url = str(work.get("doi") or work.get("id") or "").strip()
        if not url.startswith("https://"):
            continue
        authorships = work.get("authorships")
        if not isinstance(authorships, list):
            continue
        for authorship in authorships:
            if not isinstance(authorship, dict):
                continue
            if not _author_matches_institution(
                authorship, institution_name, domains, ror_ids=ror_ids
            ):
                continue
            author = authorship.get("author")
            if not isinstance(author, dict):
                continue
            disp = str(author.get("display_name") or "").strip()
            if not disp:
                continue
            role = _author_role(authorship, len(authorships))
            is_senior = _is_senior_author(authorship, len(authorships))
            multi_paper_pi = author_work_counts.get(disp.casefold(), 0) >= 2
            # Require senior/corresponding authorship or multi-paper PI evidence
            # in literature-first mode so a single-paper first-author PhD student
            # or middle co-author on a directory page is not proposed as a supervisor.
            if role != "lead" or (not is_senior and not multi_paper_pi):
                continue
            for idx, sent in enumerate(sentences):
                if _INACTIVE_PERSON_RE.search(sent) or _TRAINEE_PERSON_RE.search(sent):
                    continue
                verbatim = entity_in_sentence(disp, sent)
                if verbatim is not None:
                    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
                    if not abstract:
                        abstract = _recover_missing_abstract(url, get_json=loader)
                    finding = extract_work_phrase(abstract, title)
                    method_or_question = extract_method_or_question(
                        abstract, finding
                    ) or _extract_work_metadata_question(work, finding)
                    pt = work.get("primary_topic")
                    tid, topic_name = _work_topic_id(work)
                    shift = topic_shifts.get(tid, 0.0) if tid else 0.0
                    drift_bonus = 1 if shift > 0.0 else (-1 if shift < -0.05 else 0)
                    paper = PaperMatch(
                        title=title[:300],
                        year=year,
                        url=url,
                        finding=finding,
                        author_role=role,
                        method_or_question=method_or_question,
                        active_topic=topic_name if shift > 0.0 else "",
                    )
                    score = (
                        1 if is_senior else 0,
                        1 if bool(abstract) else 0,
                        _topic_overlap_score(
                            topic,
                            title,
                            abstract,
                            profile_terms=profile_terms,
                            primary_topic=pt if isinstance(pt, Mapping) else None,
                        ),
                        drift_bonus,
                        1 if year >= year_now - _RECENT_BONUS_YEARS else 0,
                        year,
                    )
                    candidates.append(
                        (
                            score,
                            ClassifiedSentence(
                                index=idx,
                                relevance=0.85,
                                kind="named_person",
                                entity=verbatim,
                            ),
                            paper,
                        )
                    )
                    break
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, best_sent, best_paper = candidates[0]
    return best_sent, best_paper
