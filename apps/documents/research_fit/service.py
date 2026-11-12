"""Research fit, from the student outward (2026-09-22 design).

One unit of work before letter generation: the strongest anchor the student
has becomes a profile-free topic, the institution's own domain is searched,
the pages found are fetched and split by code, a classifier picks the
sentences that name something, a three-reading judge decides alignment on
the single best pair, and a strong majority writes one pre-accepted
NarrativeInput(kind=RESEARCH_FIT) carrying its provenance. Every other path
is an outcome, recorded, never an exception: research fit never blocks a
letter (D11).

Two different spends, two different brakes. Search spend is metered in
dollars against a per-tenant daily ceiling (`spend_within_ceiling`). Model
spend is bounded by construction instead -- `MAX_PAGES_CLASSIFIED` caps the
pages one proposal may classify and judge, so a proposal costs at most
`MAX_MODEL_CALLS` -- and counted, never priced, onto
`ResearchFitOutcome.model_calls`.

The daily ceiling and the page cache live in Django's default cache -- the same
shared Redis/Valkey backend apps.ratelimit uses in production.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.funding.models import ApplicationPrompt, Institution, Program
from apps.ratelimit import rate_limited
from apps.research.discovery import retrieve_official_source
from apps.research.egress import FetchResult
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.fetch import FetchBudgetExhausted, SweepBudget
from apps.research.providers.base import ProviderUnavailable, SiteSearch, SiteSearchResult
from apps.research.providers.exa import exa_site_search
from apps.research.providers.tavily import tavily_site_search
from apps.tenancy.models import Membership

from ..audit import record_event
from ..evidence.readings import UsableReading
from ..letter_schemas import Storyline
from ..letter_shape import shape_from_prompt
from ..letter_verification import _normalize
from ..models import NarrativeInput, VerifiedFact
from .anchors import (
    Anchor,
    banned_terms,
    infer_fit_mode,
    pick_anchor,
    site_language,
    student_profile_terms,
    topic_phrase,
    translate_phrase,
)
from .classify import ClassifiedSentence, Classifier, FrontierClassifier
from .judge import is_strong, judge_alignment
from .pages import fetch_page
from .papers import (
    PaperLookup,
    PaperMatch,
    discover_literature_person_on_page,
    lookup_group_paper,
    lookup_person_paper,
)

logger = logging.getLogger(__name__)

RATE_LIMIT = 20
RATE_WINDOW_SECONDS = 3600
TOP_PAGES = 3
REUSE_DAYS = 7
_MIN_RELEVANCE = 0.5
#: How many fetched pages one proposal may spend model calls on, across every
#: anchor, domain and query. The search space is combinatorial -- up to 2
#: anchors x N domains x 2 queries x TOP_PAGES -- and each page costs one
#: classification plus, when it yields a candidate, a three-reading judgement.
#: With two anchors and two domains that is 24 pages and **96 model calls for
#: one letter**, all of them spent when NOTHING matches, which is the common
#: case; the design says "the single best pair" and judge.py said "one pair per
#: letter, so three calls". Nothing bounded it: `rate_limited` counts
#: proposals, and the daily ceiling meters search spend only, so model spend
#: had no circuit-breaker at all. Six pages is the cap because it leaves the
#: shape intact -- a second domain (D13: an awarding partner) and a second
#: anchor are still reachable -- while bounding one proposal at
#: `MAX_MODEL_CALLS`. Raising it re-opens the tail; the arithmetic is right
#: here, so do it deliberately.
MAX_PAGES_CLASSIFIED = 6
#: 2 anchors x (topic + translation) + MAX_PAGES_CLASSIFIED x (1 classification
#: + 3 judge readings). The bound, not a measurement: most pages yield no
#: candidate and are never judged.
MAX_MODEL_CALLS = 4 + MAX_PAGES_CLASSIFIED * 4

Outcome = Literal[
    "matched", "no_match", "unreadable", "provider_unavailable", "no_domain", "no_anchor",
    "rate_limited", "ceiling", "skipped_immigration", "skipped_structure",
]
_SKIPPED_STRUCTURES = {
    ApplicationPrompt.Structure.CONSORTIUM_SPECIFIC,
    ApplicationPrompt.Structure.VIDEO,
}


@dataclass(frozen=True)
class ResearchFitOutcome:
    status: Outcome
    rung: int | None
    narrative_input: NarrativeInput | None
    cost_usd: float
    #: Model calls this proposal made. Counted, not priced: a dollar figure
    #: needs a per-model price table that goes stale silently, and the cap
    #: above is the circuit-breaker. `cost_usd` remains search spend only,
    #: which is what `spend_within_ceiling` meters.
    model_calls: int = 0


def _domain_to_institution_name(program: Program) -> dict[str, str]:
    """Map each searched domain (programme institution first, then awarding
    partners per D13) to the owning institution's name so OpenAlex/ROR lookups
    filter by the institution that actually owns the matched domain."""
    mapping: dict[str, str] = {}
    institutions: list[Institution] = [program.institution] if program.institution else []
    institutions += list(program.awarding_institutions.all())
    for institution in institutions:
        try:
            host = (
                (urlsplit(institution.official_website).hostname or "")
                .lower()
                .removeprefix("www.")
            )
        except ValueError:  # malformed stored URL (e.g. a bad port): skip it, not the whole call
            continue
        if host and host not in mapping:
            mapping[host] = institution.name
    return mapping


def institution_domains(program: Program) -> tuple[str, ...]:
    """The programme's institution first, then each awarding partner (D13).
    The homepage host minus a leading www. is the domain; a public-suffix
    list is not needed because an institution's homepage is its root.
    ponytail: a homepage on a deep host narrows the search, never widens it."""
    return tuple(_domain_to_institution_name(program).keys())


def research_fit_inputs(student: Membership, program: Program) -> dict[UUID, NarrativeInput]:
    rows = NarrativeInput.objects.filter(
        student=student,
        kind=NarrativeInput.Kind.RESEARCH_FIT,
        provenance__program_id=str(program.pk),
    )
    return {row.id: row for row in rows}


def spend_within_ceiling(tenant_id: UUID, cost_usd: float) -> bool:
    key = f"research-fit:spend:{tenant_id}:{timezone.now().date().isoformat()}"
    cache.add(key, 0, timeout=86_400)
    try:
        micro = cache.incr(key, int(round(cost_usd * 1_000_000)))
    except ValueError:  # the key was evicted between add() and incr(): allow the spend (D11)
        micro = int(round(cost_usd * 1_000_000))
        cache.add(key, micro, timeout=86_400)
    return micro <= int(settings.RESEARCH_FIT_DAILY_CEILING_USD * 1_000_000)


def _finish(
    student: Membership,
    status: Outcome,
    *,
    rung: int | None = None,
    row: NarrativeInput | None = None,
    cost: float = 0.0,
    model_calls: int = 0,
) -> ResearchFitOutcome:
    record_event(actor=None, event=f"document.research_fit.{status}", object_id=student.id)
    logger.info(
        "research-fit %s for student %s: %d model calls, $%.4f search spend",
        status,
        student.id,
        model_calls,
        cost,
    )
    return ResearchFitOutcome(
        status=status, rung=rung, narrative_input=row, cost_usd=cost, model_calls=model_calls
    )


def _reusable(
    student: Membership,
    program: Program,
    topic_hash: str,
    *,
    forbidden_naming: bool = False,
) -> NarrativeInput | None:
    since = timezone.now() - timedelta(days=REUSE_DAYS)
    qs = NarrativeInput.objects.filter(
        student=student,
        kind=NarrativeInput.Kind.RESEARCH_FIT,
        provenance__program_id=str(program.pk),
        provenance__topic_hash=topic_hash,
        created_at__gte=since,
    ).order_by("-created_at")
    for row in qs:
        if forbidden_naming and isinstance(row.provenance, dict):
            if row.provenance.get("kind") in {"named_person", "research_group"}:
                continue
        return row
    return None


def _search_urls(
    query: str, domain: str, *, search: SiteSearch, fallback: SiteSearch | None
) -> SiteSearchResult:
    try:
        result = search(query=query, domain=domain)
    except ProviderUnavailable as exc:
        logger.warning(
            "research-fit primary site search degraded on %s (%s): %s",
            domain,
            type(exc).__name__,
            exc,
        )
        if fallback is None:
            raise
        return fallback(query=query, domain=domain)
    if result.urls or fallback is None:
        return result
    try:
        second = fallback(query=query, domain=domain)
    except ProviderUnavailable as exc:
        logger.warning(
            "research-fit fallback site search degraded on %s (%s): %s",
            domain,
            type(exc).__name__,
            exc,
        )
        return result
    return SiteSearchResult(
        urls=second.urls, cost_usd=result.cost_usd + second.cost_usd, provider=second.provider
    )


def _best(
    classified: tuple[ClassifiedSentence, ...],
    *,
    forbidden_naming: bool = False,
    sentences: tuple[str, ...] = (),
    profile_terms: tuple[str, ...] = (),
) -> ClassifiedSentence | None:
    blocked_kinds = {"none", "named_person", "research_group"} if forbidden_naming else {"none"}
    named = [
        c
        for c in classified
        if c.kind not in blocked_kinds and c.entity and c.relevance >= _MIN_RELEVANCE
    ]
    if not named:
        return None
    profile_set = {w.casefold() for w in profile_terms if len(w) >= 4}

    def _score(c: ClassifiedSentence) -> tuple[float, float]:
        bonus = 0.0
        if profile_set and 0 <= c.index < len(sentences):
            words = set(_normalize(sentences[c.index]).split())
            hits = sum(1 for term in profile_set if term in words)
            bonus = min(0.12, 0.03 * hits)
        return (c.relevance + bonus, c.relevance)

    named.sort(key=_score, reverse=True)
    return named[0]


def _judge_calls(claude: MessagesAPI | None) -> int:
    """What one judgement costs: two OpenAI phrasings, plus the Claude reading
    when `LETTER_JUDGE_SECOND_FAMILY` lets it through. Mirrors
    `judge_alignment`'s own gate; a reading the vendor drops still cost a
    call, so this counts calls made, not readings returned."""
    return 3 if claude is not None and settings.LETTER_JUDGE_SECOND_FAMILY else 2


def _classify_safely(
    classifier: Classifier, sentences: tuple[str, ...], *, topic: str
) -> tuple[ClassifiedSentence, ...]:
    """A classifier that is down must not block a letter (D11). A `Classifier`
    that calls out (e.g. through apps.research.decisions) may raise
    ProviderUnavailable; the frontier one already swallows its own failures
    and returns ()."""
    try:
        return classifier.classify(sentences, topic=topic)
    except ProviderUnavailable as exc:
        logger.warning("research-fit classifier unavailable (%s): %s", type(exc).__name__, exc)
        return ()


def _lookup_matched_paper(
    best: ClassifiedSentence,
    classified: tuple[ClassifiedSentence, ...],
    *,
    prefetched_paper: PaperMatch | None,
    paper_lookup: PaperLookup,
    phrase: str,
    inst_name: str,
    domain_ordered: tuple[str, ...],
    profile_terms: tuple[str, ...],
) -> PaperMatch | None:
    if best.kind == "named_person" and best.entity:
        return prefetched_paper or paper_lookup(
            entity=best.entity,
            topic=phrase,
            institution_name=inst_name,
            domains=domain_ordered,
            profile_terms=profile_terms,
        )
    if best.kind == "research_group" and best.entity:
        same_page_people = [
            c.entity
            for c in classified
            if c.kind == "named_person" and c.entity and c.relevance >= 0.4
        ]
        for person_entity in same_page_people:
            paper = paper_lookup(
                entity=person_entity,
                topic=phrase,
                institution_name=inst_name,
                domains=domain_ordered,
                profile_terms=profile_terms,
            )
            if paper is not None:
                return paper
        return lookup_group_paper(
            group_entity=best.entity,
            topic=phrase,
            institution_name=inst_name,
            domains=domain_ordered,
            profile_terms=profile_terms,
        )
    return None


def _record_matched_fit(
    *,
    student: Membership,
    program: Program,
    anchor: Anchor,
    best: ClassifiedSentence,
    classified: tuple[ClassifiedSentence, ...],
    sentence: str,
    page_url: str,
    page_digest: str,
    page_captured_at: str,
    alignment_strength: str,
    topic_hash: str,
    cost: float,
    provider: str,
    prefetched_paper: PaperMatch | None,
    paper_lookup: PaperLookup,
    phrase: str,
    inst_name: str,
    domain_ordered: tuple[str, ...],
    profile_terms: tuple[str, ...],
    storyline: Storyline | None,
) -> NarrativeInput:
    provenance: dict[str, object] = {
        "program_id": str(program.pk),
        "sentence": sentence,
        "entity": best.entity,
        "source_url": page_url,
        "page_digest": page_digest,
        # Empty for a live read; a `%Y-%m-%d` date when the
        # sentence was quoted from an Internet Archive
        # capture up to a year old. ARCHIVED is SERVED and
        # carries the ORIGINAL url, so without this the row
        # claims the institution says this today.
        "captured_at": page_captured_at,
        "kind": best.kind,
        "rung": anchor.rung,
        "anchor_fact_id": str(anchor.fact_id) if anchor.fact_id else None,
        "judgement": alignment_strength,
        "topic_hash": topic_hash,
        "cost_usd": round(cost, 6),
        "provider": provider,
    }
    paper = _lookup_matched_paper(
        best,
        classified,
        prefetched_paper=prefetched_paper,
        paper_lookup=paper_lookup,
        phrase=phrase,
        inst_name=inst_name,
        domain_ordered=domain_ordered,
        profile_terms=profile_terms,
    )
    if paper is not None:
        provenance["paper_title"] = paper.title
        provenance["paper_year"] = paper.year
        provenance["paper_url"] = paper.url
        provenance["paper_finding"] = paper.finding
        provenance["paper_author_role"] = paper.author_role
    provenance["fit_mode"] = infer_fit_mode(
        anchor_rung=anchor.rung,
        anchor_text=anchor.text,
        sentence=sentence,
        kind=best.kind,
        storyline=storyline,
        paper_finding=(
            f"{provenance.get('paper_title') or ''} {provenance.get('paper_finding') or ''}"
        ).strip(),
    )
    return NarrativeInput.objects.create(
        student=student,
        kind=NarrativeInput.Kind.RESEARCH_FIT,
        text=sentence,
        proposed_by=NarrativeInput.ProposedBy.ENGINE,
        confirmed_at=timezone.now(),
        provenance=provenance,
    )


def propose_research_fit(
    *,
    student: Membership,
    program: Program,
    prompt: ApplicationPrompt,
    facts: dict[UUID, VerifiedFact],
    storyline: Storyline | None,
    readings: tuple[UsableReading, ...] = (),
    parser: ResponsesAPI | None = None,
    claude: MessagesAPI | None = None,
    classifier: Classifier | None = None,
    search: SiteSearch = exa_site_search,
    fallback_search: SiteSearch | None = tavily_site_search,
    fetch: Callable[[str], FetchResult] = retrieve_official_source,
    paper_lookup: PaperLookup = lookup_person_paper,
) -> ResearchFitOutcome:
    if prompt.immigration:
        return _finish(student, "skipped_immigration")
    if prompt.structure in _SKIPPED_STRUCTURES:
        return _finish(student, "skipped_structure")
    if rate_limited(
        "research-fit", student.id, limit=RATE_LIMIT, window_seconds=RATE_WINDOW_SECONDS
    ):
        return _finish(student, "rate_limited")
    if not spend_within_ceiling(student.tenant_id, 0.0):
        return _finish(student, "ceiling")
    domain_institutions = _domain_to_institution_name(program)
    domains = tuple(domain_institutions.keys())
    if not domains:
        return _finish(student, "no_domain")
    strongest = pick_anchor(facts, storyline, readings=readings)
    if strongest is None:
        return _finish(student, "no_anchor")
    anchors: list[Anchor] = [strongest]
    if strongest.rung != 4 and storyline is not None:
        anchors.append(Anchor(rung=4, text=storyline.theme, fact_id=None))
    forbidden_naming = shape_from_prompt(prompt).naming == "FORBIDDEN"

    if parser is None:
        from openai import OpenAI, OpenAIError

        try:
            parser = cast(ResponsesAPI, OpenAI().responses)
        except OpenAIError:
            # openai.OpenAIError is not a ValueError, so a missing/invalid
            # key or bad base URL would otherwise escape as a raw SDK
            # exception and block the letter -- same escape class as
            # letters.py::generate_letter's client construction (D11).
            logger.warning("research-fit OpenAI client could not be constructed")
            return _finish(student, "no_match")
    if classifier is None:
        classifier = FrontierClassifier(parser, student_id=str(student.id))
    student_id = str(student.id)
    banned = banned_terms(facts)
    profile_terms = student_profile_terms(facts, storyline, readings=readings)
    language = site_language(program)

    cost = 0.0
    model_calls = 0
    # D15: every page read below is a billable vendor credit, and
    # `spend_within_ceiling` meters SEARCH spend only. One budget per proposal
    # bounds the fetch half, and its dollars are folded into the same tenant
    # ceiling as the search dollars -- so the ceiling finally sees the whole
    # cost of a proposal rather than half of it.
    fetch_budget = SweepBudget(settings.RESEARCH_FIT_FETCH_CREDITS)
    fetch_spent = 0.0
    saw_unreadable = False
    pages_tried = 0
    pages_read = 0
    providers_failed = 0
    provider_calls = 0
    # `pages_read` is the budget, and it is checked at every level of the
    # search: once it is spent there is nothing left to classify, so a further
    # search call would only buy URLs nobody can read.
    for anchor in anchors:
        if pages_read >= MAX_PAGES_CLASSIFIED:
            break
        phrase = topic_phrase(anchor, parser=parser, student_id=student_id, banned=banned)
        model_calls += 1
        if not phrase:
            continue
        topic_hash = hashlib.sha256(phrase.encode()).hexdigest()
        reused = _reusable(student, program, topic_hash, forbidden_naming=forbidden_naming)
        if reused is not None and reused.provenance is not None:
            return _finish(
                student,
                "matched",
                rung=int(reused.provenance["rung"]),
                row=reused,
                cost=0.0,
                model_calls=model_calls,
            )
        translated_local: str | None = None
        did_translate = False
        seen_urls: set[str] = set()
        for domain in domains:
            if pages_read >= MAX_PAGES_CLASSIFIED:
                break
            query_slots = (False, True) if language else (False,)
            for is_local_slot in query_slots:
                if pages_read >= MAX_PAGES_CLASSIFIED:
                    break
                if is_local_slot and language:
                    if not did_translate:
                        did_translate = True
                        local = translate_phrase(
                            phrase,
                            language=language,
                            parser=parser,
                            student_id=student_id,
                            banned=banned,
                        )
                        model_calls += 1
                        if local and local != phrase:
                            translated_local = local
                    if not translated_local:
                        continue
                    query = translated_local
                else:
                    query = phrase
                provider_calls += 1
                try:
                    found = _search_urls(query, domain, search=search, fallback=fallback_search)
                except ProviderUnavailable as exc:
                    logger.warning(
                        "research-fit site search unavailable on %s (%s): %s",
                        domain,
                        type(exc).__name__,
                        exc,
                    )
                    providers_failed += 1
                    continue
                cost += found.cost_usd
                if not spend_within_ceiling(student.tenant_id, found.cost_usd):
                    return _finish(student, "ceiling", cost=cost, model_calls=model_calls)
                for url in found.urls[:TOP_PAGES]:
                    if pages_read >= MAX_PAGES_CLASSIFIED:
                        break
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    pages_tried += 1
                    try:
                        page, outcome = fetch_page(
                            url,
                            domain=domain,
                            tenant_id=student.tenant_id,
                            fetch=fetch,
                            budget=fetch_budget,
                        )
                    except FetchBudgetExhausted:
                        # The same outcome the dollar ceiling gives, because it
                        # means the same thing to the student: this proposal
                        # stopped on cost. Charged first -- the credits are
                        # gone whether or not the call was within the cap.
                        cost += fetch_budget.usd() - fetch_spent
                        spend_within_ceiling(student.tenant_id, fetch_budget.usd() - fetch_spent)
                        return _finish(student, "ceiling", cost=cost, model_calls=model_calls)
                    charged = fetch_budget.usd() - fetch_spent
                    if charged:
                        fetch_spent = fetch_budget.usd()
                        cost += charged
                        if not spend_within_ceiling(student.tenant_id, charged):
                            return _finish(student, "ceiling", cost=cost, model_calls=model_calls)
                    if page is None:
                        saw_unreadable = saw_unreadable or outcome == "unreadable"
                        continue
                    pages_read += 1
                    classified = _classify_safely(classifier, page.sentences, topic=phrase)
                    model_calls += 1
                    inst_name = domain_institutions.get(domain) or (
                        program.institution.name if program.institution else ""
                    )
                    domain_ordered = (domain, *tuple(d for d in domains if d != domain))
                    best = _best(
                        classified,
                        forbidden_naming=forbidden_naming,
                        sentences=page.sentences,
                        profile_terms=profile_terms,
                    )
                    prefetched_paper: PaperMatch | None = None
                    if best is None and not forbidden_naming:
                        lit_found = discover_literature_person_on_page(
                            page.sentences,
                            topic=phrase,
                            institution_name=inst_name,
                            domains=domain_ordered,
                            profile_terms=profile_terms,
                        )
                        if lit_found is not None:
                            best, prefetched_paper = lit_found
                    if best is None:
                        continue
                    sentence = page.sentences[best.index]
                    judge_sentence = (
                        f"{sentence} ({prefetched_paper.title}: {prefetched_paper.finding})"
                        if prefetched_paper is not None
                        else sentence
                    )
                    judge_anchor_text = (
                        f"{anchor.text} (target training gap: {storyline.gap})"
                        if best.kind == "module_or_track"
                        and storyline is not None
                        and storyline.gap
                        else anchor.text
                    )
                    alignment = judge_alignment(
                        parser=parser,
                        claude=claude,
                        student_id=student_id,
                        anchor_text=judge_anchor_text,
                        sentence=judge_sentence,
                    )
                    model_calls += _judge_calls(claude)
                    if not is_strong(alignment):
                        continue
                    row = _record_matched_fit(
                        student=student,
                        program=program,
                        anchor=anchor,
                        best=best,
                        classified=classified,
                        sentence=sentence,
                        page_url=page.url,
                        page_digest=page.digest,
                        page_captured_at=page.captured_at,
                        alignment_strength=alignment.strength,
                        topic_hash=topic_hash,
                        cost=cost,
                        provider=found.provider,
                        prefetched_paper=prefetched_paper,
                        paper_lookup=paper_lookup,
                        phrase=phrase,
                        inst_name=inst_name,
                        domain_ordered=domain_ordered,
                        profile_terms=profile_terms,
                        storyline=storyline,
                    )
                    logger.info(
                        "research-fit matched rung %d for student %s", anchor.rung, student.id
                    )
                    return _finish(
                        student,
                        "matched",
                        rung=anchor.rung,
                        row=row,
                        cost=cost,
                        model_calls=model_calls,
                    )
    if provider_calls and providers_failed == provider_calls:
        return _finish(student, "provider_unavailable", cost=cost, model_calls=model_calls)
    if pages_tried and not pages_read:
        # Every page the search found failed to fetch, so NOTHING was read.
        # That came back as "no_match" -- "we read the institution's pages and
        # nothing aligned" -- which is the silence-vs-absence confusion
        # CLAUDE.md pins for the programme-page reader, one layer along (PR #114
        # review). No claim was invented either way; it is the label that lied.
        return _finish(student, "unreadable", cost=cost, model_calls=model_calls)
    if saw_unreadable:
        return _finish(student, "unreadable", cost=cost, model_calls=model_calls)
    return _finish(student, "no_match", cost=cost, model_calls=model_calls)


def recheck_research_fit(
    inputs: dict[UUID, NarrativeInput],
    *,
    fetch: Callable[[str], FetchResult] = retrieve_official_source,
) -> tuple[UUID, ...]:
    """People move (design D9): at approval, re-fetch each cited page and
    confirm it still carries the entity. An unchanged digest passes without
    reading; a changed page passes if the entity is still on it. A page that
    is genuinely readable but has dropped the entity, or one that read as
    `unreadable`, is stale and the counselor sees the quote beside the flag.
    A vendor outage (`fetch_failed` -- the page was never actually read) is
    unknown, not stale: flagging it the same as a dropped name would dump
    every citation into the counselor queue on a third-party hiccup, the
    wrong-way degradation D11 forbids. Nothing below may raise out of this
    function -- it runs from `mark_letter_ready` by default, so an exception
    here (a malformed stored URL, an unexpected shape from the page
    pipeline) must degrade one row to 'not stale' rather than lose the
    batch, never block the letter."""
    stale: list[UUID] = []
    for input_id, entry in inputs.items():
        if entry.kind != NarrativeInput.Kind.RESEARCH_FIT or not entry.provenance:
            continue
        try:
            provenance = entry.provenance
            source_url = str(provenance.get("source_url") or "")
            domain = (urlsplit(source_url).hostname or "").removeprefix("www.")
            page, outcome = fetch_page(
                source_url,
                domain=domain,
                tenant_id=entry.tenant_id,
                fetch=fetch,
                # Never the cache here. Its TTL is a week, and propose and
                # approve routinely fall inside one -- so the re-check compared
                # the propose-time page against its own propose-time digest,
                # which is true by construction, and a professor who had left
                # the page was reported not stale (PR #114 review, measured).
                # The whole point of D9 is that the page is read AGAIN.
                use_cache=False,
            )
            if page is None:
                # "unreadable" and "off_domain" both mean the page was reached
                # and read -- a shell page or a redirect off the institution's
                # domain -- so the citation is stale. "fetch_failed" means the
                # page was never read at all (vendor outage, timeout): unknown,
                # not stale, or a third-party hiccup floods the counselor queue.
                if outcome in ("unreadable", "off_domain"):
                    stale.append(input_id)
                continue
            if page.digest == provenance.get("page_digest"):
                continue
            entity = _normalize(str(provenance.get("entity") or ""))
            if not any(entity and entity in _normalize(s) for s in page.sentences):
                stale.append(input_id)
        except Exception:
            logger.warning("research-fit recheck failed for input %s", input_id, exc_info=True)
    return tuple(stale)
