"""End-to-end scrape pipeline orchestrators."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import replace

from django.utils import timezone

from apps.funding.models import (
    CostComponent,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
    ProgramStatement,
)
from apps.research.card_engine import Limit
from apps.research.card_engine.engine import Transport
from apps.research.card_engine.readers import (
    ReadersNotConfigured,
    Stack,
    StackMisconfigured,
    require_keys,
    stack,
)
from apps.research.card_engine.screen import Screen

from .arbitration import needs_high_risk_arbitration, refine_with_dual_readers
from .extractors import extract_tier0_programme_facts
from .persistence import _ensure_source_and_snapshot, persist_programme_scrape
from .specs import (
    InstitutionBaseProfile,
    ProgrammeBundle,
    ProgrammeScrapeResult,
    ScrapeStage,
)
from .sublinks import (
    build_programme_bundle,
    classify_programme_sublinks,
    is_page_unchanged,
)

logger = logging.getLogger(__name__)


def _resolve_arbitration_screen(
    bundle: ProgrammeBundle,
    *,
    screen: Screen | Callable[..., Screen] | None,
    limit: Limit | None,
    readers: Stack | None,
    transport: Transport | None,
) -> Screen | None:
    if screen is None or limit is None:
        return None
    if isinstance(screen, Screen):
        return screen
    if callable(screen):
        if transport is None:
            try:
                require_keys(readers or stack())
            except (ReadersNotConfigured, StackMisconfigured):
                return None
        try:
            cleared = screen(bundle.section, limit=limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("programme scraper screen failed: %s", exc)
            return None
        return cleared if isinstance(cleared, Screen) and cleared.status == "clear" else None
    return None


def scrape_fetched_programme_page(
    program: Program,
    *,
    source: OfficialSource,
    snapshot: OfficialSourceSnapshot,
    html: bytes | str,
    evidence_strength: str = "DIRECT",
    visibility: str = "STUDENT_FACING",
    screen: Screen | Callable[..., Screen] | None = None,
    limit: Limit | None = None,
    readers: Stack | None = None,
    transport: Transport | None = None,
    now: dt.datetime | None = None,
) -> ProgrammeScrapeResult:
    """Zero-cost inline Stage A (`gate_and_money`) scraper for an already-fetched programme page.

    Used by `run_discovery` right after `write_catalog_entry` succeeds so structured tuition
    (`CostComponent`) and application-fee figures from Rung 0 JSON-LD, 2D HTML tables, and `<dl>`
    lists are persisted onto `program` using the existing `source` and `snapshot` without extra
    network fetches or LLM calls unless optional `screen` and `limit` are supplied for
    high-risk arbitration.
    """
    raw_bytes = html.encode("utf-8", errors="replace") if isinstance(html, str) else html
    if not raw_bytes or raw_bytes.startswith(b"%PDF"):
        return ProgrammeScrapeResult(
            duration_months=program.duration_months,
            teaching_languages=tuple(program.teaching_languages),
            costs=(),
            eligibility=(),
            statements=(),
        )
    checked_at = now or timezone.now()
    bundle = build_programme_bundle([(source.canonical_url, raw_bytes)], title=program.name)
    result = extract_tier0_programme_facts(bundle)

    if screen is not None and limit is not None and needs_high_risk_arbitration(result):
        resolved_screen = _resolve_arbitration_screen(
            bundle,
            screen=screen,
            limit=limit,
            readers=readers,
            transport=transport,
        )
        if resolved_screen is not None:
            result = refine_with_dual_readers(
                bundle,
                result,
                screen=resolved_screen,
                limit=limit,
                readers=readers,
                transport=transport,
            )

    # When running inline at Tier 0 without LLM arbitration (or when arbitration left a slot
    # unresolved), do not persist an unresolved conflicting TUITION guess unless it came from
    # a unanimous 2D structured table/DL/JSON-LD.
    safe_costs = tuple(
        cost_spec
        for cost_spec in result.costs
        if not (
            cost_spec.kind == "TUITION"
            and (
                "conditional_free_tuition" in result.high_risk_flags
                or ("tuition" in result.unresolved_slots and not cost_spec.from_structured)
            )
        )
    )
    persist_programme_scrape(
        program=program,
        result=replace(result, costs=safe_costs),
        pages_by_url={source.canonical_url: raw_bytes},
        stage="full",
        now=checked_at,
        source=source,
        snapshot=snapshot,
        evidence_strength=evidence_strength,
        visibility=visibility,
    )

    return result


def scrape_programme_pages(
    program: Program,
    front_url: str,
    front_html: bytes | str,
    *,
    fetch_fn: Callable[[str], bytes | str | None] | None = None,
    stage: ScrapeStage = "full",
    base_profile: InstitutionBaseProfile | None = None,
    screen: Screen | Callable[..., Screen] | None = None,
    limit: Limit | None = None,
    readers: Stack | None = None,
    transport: Transport | None = None,
    derive_fn: Callable[[Program, str, OfficialSourceSnapshot, str], object] | None = None,
    now: dt.datetime | None = None,
) -> ProgrammeScrapeResult:
    """Orchestrate the full two-stage programme scraping pipeline for `program`:
    1. SHA-256 Digest Gate (`is_page_unchanged`) short-circuits unchanged pages for $0.00.
    2. Zero-cost sublink router (`classify_programme_sublinks`) fetches up to 1 sub-page per slot.
    3. Multi-page candidate bundle (`build_programme_bundle`) merges front-door + sub-pages.
    4. Tier 0 AST grammar extractor (`extract_tier0_programme_facts`) resolves facts at $0.00.
    5. Optional Tier 1/2 dual-reader + risk-asymmetric arbitrator (`refine_with_dual_readers`).
    6. Catalogue persistence (`persist_programme_scrape`) + optional `derive_fn` hook.
    """
    has_costs = CostComponent.objects.filter(program=program).exists()
    has_stmts = (
        True
        if stage == "gate_and_money"
        else ProgramStatement.objects.filter(program=program, kind="DOCUMENT").exists()
    )
    if is_page_unchanged(front_url, front_html) and has_costs and has_stmts:
        return ProgrammeScrapeResult(
            duration_months=program.duration_months,
            teaching_languages=tuple(program.teaching_languages),
            costs=(),
            eligibility=(),
            statements=(),
            cv_format=program.cv_format_requirement,
            cv_format_source_url=program.cv_format_source_url,
            letter_required=program.letter_required,
            cv_constraints=tuple(program.cv_constraints),
            cv_directives=tuple(program.cv_directives),
            file_rules=tuple(program.file_rules),
            referee_requirements=tuple(program.referee_requirements),
            portfolio_led=program.portfolio_led,
            cost_usd=0.0,
        )

    pages: list[tuple[str, bytes | str]] = [(front_url, front_html)]
    if fetch_fn is not None:
        sublinks = classify_programme_sublinks(front_url, front_html)
        for sub_url in sublinks.as_tuple(stage=stage):
            if sub_url == front_url:
                continue
            try:
                sub_html = fetch_fn(sub_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to fetch programme sublink %s: %s", sub_url, exc)
                sub_html = None
            if sub_html:
                pages.append((sub_url, sub_html))

    bundle = build_programme_bundle(pages, title=program.name, base_profile=base_profile)
    result = extract_tier0_programme_facts(bundle, base_profile=base_profile)

    if screen is not None and limit is not None and needs_high_risk_arbitration(result):
        resolved_screen = _resolve_arbitration_screen(
            bundle,
            screen=screen,
            limit=limit,
            readers=readers,
            transport=transport,
        )
        if resolved_screen is not None:
            result = refine_with_dual_readers(
                bundle,
                result,
                screen=resolved_screen,
                limit=limit,
                readers=readers,
                transport=transport,
            )

    persist_programme_scrape(
        program,
        result,
        pages_by_url=dict(pages),
        stage=stage,
        now=now,
    )
    if derive_fn is not None and stage in ("deep_documents", "full"):
        checked_at = now or timezone.now()
        _, snap = _ensure_source_and_snapshot(front_url, front_html, now=checked_at)
        combined_text = "\n".join(line.text for line in bundle.section.lines)
        derive_fn(program, combined_text, snap, bundle.section.lang)
        program.refresh_from_db()
    return result


__all__ = [
    "scrape_fetched_programme_page",
    "scrape_programme_pages",
]
