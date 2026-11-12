"""Catalogue and evidence persistence for programme scraping."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone

from apps.funding.models import (
    CostComponent,
    CostComponentEvidenceClaim,
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
    Period,
    Program,
    ProgramEvidenceClaim,
    ProgramStatement,
)
from apps.research.harvest import content_digest
from apps.research.hosts import registrable_domain

from .specs import CostComponentSpec, ProgrammeScrapeResult, ScrapeStage
from .sublinks import _safe_canonical_url


def _ensure_source_and_snapshot(
    url: str,
    html: bytes | str | None,
    *,
    now: dt.datetime,
) -> tuple[OfficialSource, OfficialSourceSnapshot]:
    norm_url = _safe_canonical_url(url)
    domain = registrable_domain(norm_url) or urlsplit(norm_url).hostname or "unknown"
    source, _ = OfficialSource.objects.get_or_create(
        canonical_url=norm_url,
        defaults={
            "publisher": domain,
            "source_type": OfficialSource.Type.PROGRAM,
        },
    )
    raw_bytes = (
        html.encode("utf-8")
        if isinstance(html, str)
        else (html if html is not None else norm_url.encode("utf-8"))
    )
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    c_sha = content_digest(raw_bytes) if html is not None else ""
    snapshot = OfficialSourceSnapshot.objects.filter(source=source, sha256=raw_sha).first()
    if snapshot is None:
        snapshot = OfficialSourceSnapshot.objects.create(
            source=source,
            s3_key=f"official-sources/programme/{domain}/{raw_sha[:16]}",
            s3_version_id="1",
            sha256=raw_sha,
            content_sha256=c_sha,
            final_url=norm_url,
            redirect_chain=[],
            retrieved_at=now,
            admissions_cycle=f"{now.year}-{now.year + 1}",
            content_type="text/html",
            byte_size=max(1, len(raw_bytes)),
            discovery_technique="programme_scraper",
        )
    return source, snapshot


@transaction.atomic
def persist_programme_scrape(
    program: Program,
    result: ProgrammeScrapeResult,
    *,
    pages_by_url: Mapping[str, bytes | str] | None = None,
    stage: ScrapeStage = "full",
    now: dt.datetime | None = None,
) -> None:
    """Idempotently persist `ProgrammeScrapeResult` onto `Program`, `CostComponent`,
    `ProgramStatement`, and `OfficialEvidenceClaim` rows."""
    checked_at = now or timezone.now()
    html_map = pages_by_url or {}
    fallback_url = (
        next(iter(html_map.keys()), "")
        or f"https://{program.origin_domain or program.evidence_domain or 'example.org'}/"
    )

    update_fields: list[str] = []
    if result.duration_months is not None and 1 <= result.duration_months <= 60:
        if program.duration_months != result.duration_months:
            program.duration_months = result.duration_months
            update_fields.append("duration_months")
    if result.teaching_languages:
        merged_langs = list(
            dict.fromkeys([*program.teaching_languages, *result.teaching_languages])
        )[:10]
        if merged_langs != list(program.teaching_languages):
            program.teaching_languages = merged_langs
            update_fields.append("teaching_languages")

    if stage in ("deep_documents", "full"):
        if result.cv_format != "any" and program.cv_format_requirement != result.cv_format:
            program.cv_format_requirement = result.cv_format
            program.cv_format_confidence = Program.CVFormatConfidence.EXTRACTED
            update_fields.extend(["cv_format_requirement", "cv_format_confidence"])
        if result.cv_format_source_url and not program.cv_format_source_url:
            program.cv_format_source_url = result.cv_format_source_url
            update_fields.append("cv_format_source_url")
        if (
            result.letter_required != "unknown"
            and program.letter_required != result.letter_required
        ):
            program.letter_required = result.letter_required
            update_fields.append("letter_required")
        if result.cv_constraints and not program.cv_constraints:
            program.cv_constraints = list(result.cv_constraints)
            update_fields.append("cv_constraints")
        if result.cv_directives and not program.cv_directives:
            program.cv_directives = list(result.cv_directives)
            update_fields.append("cv_directives")
        if result.file_rules and not program.file_rules:
            program.file_rules = list(result.file_rules)
            update_fields.append("file_rules")
        if result.referee_requirements and not program.referee_requirements:
            program.referee_requirements = list(result.referee_requirements)
            update_fields.append("referee_requirements")
        if result.portfolio_led and not program.portfolio_led:
            program.portfolio_led = True
            update_fields.append("portfolio_led")

    if update_fields:
        program.save(update_fields=list(dict.fromkeys(update_fields)))

    # Persist CostComponents (TUITION, APPLICATION_FEE), preferring INTERNATIONAL > ALL > EU
    _audience_rank = {"INTERNATIONAL": 0, "ALL": 1, "EU_DOMESTIC": 2}
    canonical_costs_by_kind: dict[str, CostComponentSpec] = {}
    for cost_spec in result.costs:
        existing_spec = canonical_costs_by_kind.get(cost_spec.kind)
        if existing_spec is None or _audience_rank.get(cost_spec.audience, 9) < _audience_rank.get(
            existing_spec.audience, 9
        ):
            canonical_costs_by_kind[cost_spec.kind] = cost_spec

    for cost_spec in canonical_costs_by_kind.values():
        src_url = cost_spec.source_url or fallback_url
        source, snapshot = _ensure_source_and_snapshot(
            src_url, html_map.get(src_url), now=checked_at
        )
        period_val = (
            cost_spec.period
            if cost_spec.period in Period.values
            else Period.ANNUAL
        )
        cost_row, _ = CostComponent.objects.update_or_create(
            program=program,
            kind=cost_spec.kind,
            defaults={
                "amount": cost_spec.amount,
                "currency": cost_spec.currency,
                "period": period_val,
            },
        )
        claim, _ = OfficialEvidenceClaim.objects.update_or_create(
            source=source,
            snapshot=snapshot,
            claim_class="TUITION",
            claim=cost_spec.quote.text[:4000],
            defaults={
                "evidence_strength": "DIRECT",
                "visibility": "STUDENT_FACING",
                "last_checked_at": checked_at,
            },
        )
        CostComponentEvidenceClaim.objects.get_or_create(
            cost_component=cost_row, evidence_claim=claim
        )
        ProgramEvidenceClaim.objects.get_or_create(program=program, evidence_claim=claim)

    # Persist Eligibility & Deadline Evidence Claims
    for elig_spec in result.eligibility:
        src_url = elig_spec.source_url or fallback_url
        source, snapshot = _ensure_source_and_snapshot(
            src_url, html_map.get(src_url), now=checked_at
        )
        c_class = "DEADLINE" if elig_spec.kind == "DEADLINE" else "ELIGIBILITY"
        claim, _ = OfficialEvidenceClaim.objects.update_or_create(
            source=source,
            snapshot=snapshot,
            claim_class=c_class,
            claim=f"{elig_spec.label}: {elig_spec.quote.text}"[:4000],
            defaults={
                "evidence_strength": "DIRECT",
                "visibility": "STUDENT_FACING",
                "last_checked_at": checked_at,
            },
        )
        ProgramEvidenceClaim.objects.get_or_create(program=program, evidence_claim=claim)

    # Persist Document & Requirement Statements (Stage B / full, plus Scholarship Status in Stage A)
    stmts_to_persist = (
        result.statements
        if stage in ("deep_documents", "full")
        else tuple(
            s
            for s in result.statements
            if s.label.startswith("Scholarship / Funding Status")
        )
    )
    if stmts_to_persist:
        existing_norms = {
            " ".join(t.casefold().split())
            for t in ProgramStatement.objects.filter(program=program).values_list("text", flat=True)
        }
        for stmt_spec in stmts_to_persist:
            norm_text = " ".join(stmt_spec.text.casefold().split())
            if norm_text in existing_norms:
                continue
            existing_norms.add(norm_text)
            src_url = stmt_spec.source_url or fallback_url
            _, snapshot = _ensure_source_and_snapshot(
                src_url, html_map.get(src_url), now=checked_at
            )
            ProgramStatement.objects.create(
                program=program,
                snapshot=snapshot,
                kind=stmt_spec.kind,
                requirement=stmt_spec.requirement,
                text=stmt_spec.text[:1000],
                label=stmt_spec.label[:200],
            )

    # Record the primary front-door snapshot so `is_page_unchanged` hits on the next run
    if fallback_url in html_map:
        _ensure_source_and_snapshot(fallback_url, html_map[fallback_url], now=checked_at)


__all__ = [
    "_ensure_source_and_snapshot",
    "persist_programme_scrape",
]
