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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from django.conf import settings
from django.core.cache import cache

from apps.research.egress import fetch_json_api

from .classify import _INACTIVE_PERSON_RE, ClassifiedSentence, entity_in_sentence
from .split import page_sentences

logger = logging.getLogger(__name__)

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
CROSSREF_WORKS_URL = "https://api.crossref.org/works/"
PAPER_CACHE_TTL_SECONDS = 7 * 24 * 3600
_MAX_PAPER_AGE_YEARS = 6
_RECENT_BONUS_YEARS = 3
_JATS_TAG_RE = re.compile(r"<[^>]+>")
_GROUP_STOP_WORDS = frozenset({
    "chair", "group", "laboratory", "department", "institute", "institut",
    "center", "centre", "research", "division", "unit", "faculty", "school",
    "section", "team", "working", "lehrstuhl", "fachgebiet", "abteilung",
})
_TITLE_PREFIX = re.compile(
    r"^(?:prof(?:essor)?|dr(?:\.-?ing)?|mr|ms|mrs|assoc(?:iate)?|asst|assistant|ir|ing|univ|habil|rer|nat|phil|med|sc|h\.?c\.?)"
    r"[.\-\s]+",
    re.IGNORECASE,
)
_NON_ALPHA = re.compile(r"[^\w\s-]", re.UNICODE)
_WORK_PHRASE_CUE_RE = re.compile(
    r"\b(?:"
    r"we\s+(?:show|propose|find|demonstrate|prove|derive|introduce|present|develop|establish)|"
    r"results\s+(?:indicate|show|demonstrate)|"
    r"our\s+(?:results|method|approach|analysis|framework)\s+(?:shows?|demonstrates?|achieves?)|"
    r"this\s+(?:paper|study|work)\s+(?:presents|shows|proposes|demonstrates|introduces)"
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


PaperLookup = Callable[..., PaperMatch | None]


def strip_academic_titles(entity: str) -> str:
    text = entity.strip()
    while True:
        stripped = _TITLE_PREFIX.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    return text


def person_matches_author(entity: str, author_names: tuple[str, ...]) -> bool:
    """Whether `entity` (e.g. 'Prof. Dr. M. Kaya' or 'Prof. Jane Smith')
    matches one of an OpenAlex author's display names."""
    clean_entity = _NON_ALPHA.sub(" ", strip_academic_titles(entity)).casefold().split()
    if not clean_entity:
        return False
    surname = clean_entity[-1]
    if len(surname) < 2:
        return False
    given = clean_entity[:-1]
    for raw_name in author_names:
        tokens = _NON_ALPHA.sub(" ", raw_name).casefold().split()
        if not tokens or tokens[-1] != surname:
            continue
        if not given:
            return True
        author_given = tokens[:-1]
        if not author_given:
            continue
        first_want = given[0]
        first_have = author_given[0]
        if first_want == first_have:
            return True
        if len(first_want) == 1 and first_have.startswith(first_want):
            return True
        if len(first_have) == 1 and first_want.startswith(first_have):
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


def _topic_overlap_score(
    topic: str,
    title: str,
    abstract: str,
    profile_terms: tuple[str, ...] = (),
) -> int:
    topic_words = {
        w for w in _NON_ALPHA.sub(" ", topic).casefold().split() if len(w) >= 4
    }
    profile_words = {
        w.casefold() for w in profile_terms if len(w) >= 4
    } - topic_words
    if not topic_words and not profile_words:
        return 0
    haystack_set = set(_NON_ALPHA.sub(" ", f"{title} {abstract}").casefold().split())
    return (
        sum(2 for w in topic_words if w in haystack_set)
        + sum(1 for w in profile_words if w in haystack_set)
    )


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
    and student-profile vocabulary overlap) and soft recency second (spec
    2026-10-14 §6.2)."""
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
    candidates: list[tuple[tuple[int, int, int, int, int], PaperMatch]] = []
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
        if not abstract and url.startswith("https://doi.org/10."):
            abstract = _crossref_abstract(url, get_json=loader)
        finding = extract_work_phrase(abstract, title)
        score = (
            1 if matched_role == "lead" else 0,
            1 if bool(abstract) else 0,
            _topic_overlap_score(topic, title, abstract, profile_terms=profile_terms),
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
                    author_role=matched_role,
                ),
            )
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
        if not abstract and url.startswith("https://doi.org/10."):
            abstract = _crossref_abstract(url, get_json=loader)
        text_tokens = set(_NON_ALPHA.sub(" ", f"{title} {abstract}").casefold().split())
        aff_group_hits = len(group_tokens & aff_tokens)
        text_group_hits = len(group_tokens & text_tokens)
        if aff_group_hits == 0 and text_group_hits == 0:
            continue
        finding = extract_work_phrase(abstract, title)
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
    `sentences` (and is not marked emeritus/visiting/on leave)."""
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
    candidates: list[
        tuple[tuple[int, int, int, int], ClassifiedSentence, PaperMatch]
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
            # Only propose lead/corresponding authors in literature-first mode
            # so a PhD student or middle co-author on a directory page is not
            # proposed as a supervisor.
            if role != "lead":
                continue
            for idx, sent in enumerate(sentences):
                if _INACTIVE_PERSON_RE.search(sent):
                    continue
                verbatim = entity_in_sentence(disp, sent)
                if verbatim is not None:
                    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
                    if not abstract and url.startswith("https://doi.org/10."):
                        abstract = _crossref_abstract(url, get_json=loader)
                    paper = PaperMatch(
                        title=title[:300],
                        year=year,
                        url=url,
                        finding=extract_work_phrase(abstract, title),
                        author_role=role,
                    )
                    score = (
                        1 if bool(abstract) else 0,
                        _topic_overlap_score(
                            topic, title, abstract, profile_terms=profile_terms
                        ),
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
