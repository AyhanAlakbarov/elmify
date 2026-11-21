"""Sublink classification, HTML page line extraction, bundle construction, and
institution base profile extraction.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Collection, Sequence
from decimal import Decimal
from urllib.parse import urljoin, urlsplit

import lxml.html
from lxml.etree import ParserError, strip_elements

from apps.documents.letter_terms import detect_language
from apps.funding.models import OfficialSourceSnapshot
from apps.research.candidates import Line
from apps.research.card_engine import Quote, Section, locate
from apps.research.card_engine.engine import MAX_SECTION_CHARS
from apps.research.card_funding.awards import page_lines as split_page_lines
from apps.research.discovery import canonicalize_url
from apps.research.egress import FetchResult
from apps.research.harvest import content_digest
from apps.research.hosts import registrable_domain
from apps.research.pipeline import _names_another_degree
from apps.research.reader import html_lang, readable_text
from apps.research.structured_html import extract_jsonld_lines, extract_table_and_dl_lines

from .extractors import (
    _amount_audience_on_line,
    _candidates_with_header_currency,
    _period_from_context,
    extract_tier0_programme_facts,
)
from .patterns import (
    _ADMISSION_LINK_RE,
    _BINARY_ASSET_EXT_RE,
    _CATEGORY_REF_RE,
    _DOCUMENT_LINK_RE,
    _SCHOLARSHIP_LINK_RE,
    _TUITION_LINK_RE,
)
from .specs import (
    CostComponentSpec,
    InstitutionBaseProfile,
    ProgrammeBundle,
    ProgrammeSublinks,
)

logger = logging.getLogger(__name__)


def classify_programme_sublinks(
    base_url: str,
    html: bytes | str,
    *,
    allowed_domains: Collection[str] | None = None,
) -> ProgrammeSublinks:
    """Classify `<a href>` links on `html` into the 4 sub-page slots at $0.00 cost."""
    raw = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    if not raw or not raw.strip():
        return ProgrammeSublinks()
    try:
        doc = lxml.html.fromstring(raw)
    except (ParserError, ValueError) as error:
        logger.debug(
            "programme sublink HTML parse degraded for %s (%s: %s)",
            base_url,
            type(error).__name__,
            error,
        )
        return ProgrammeSublinks()
    strip_elements(doc, "footer", with_tail=False)

    base_domain = registrable_domain(base_url)
    domains = set(allowed_domains) if allowed_domains else ({base_domain} if base_domain else set())
    base_clean = base_url.split("#", 1)[0].rstrip("/")
    base_path = urlsplit(base_clean).path.rstrip("/")

    best: dict[str, tuple[int, str]] = {}

    for a_node in doc.xpath("//a[@href]"):
        href = (a_node.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full_url = urljoin(base_url, href).split("#", 1)[0]
        parsed = urlsplit(full_url)
        if parsed.scheme not in ("http", "https"):
            continue
        if _BINARY_ASSET_EXT_RE.search(parsed.path):
            continue
        if domains and registrable_domain(full_url) not in domains:
            continue
        if full_url.rstrip("/") == base_clean:
            continue
        if _names_another_degree(full_url):
            continue

        anchor_text = re.sub(r"\s+", " ", str(a_node.text_content() or "")).strip()
        path_and_query = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
        combined = f"{path_and_query} {anchor_text}"
        is_child_path = bool(
            base_path
            and (
                parsed.path.startswith(f"{base_path}/")
                or (parsed.path.rstrip("/") == base_path and bool(parsed.query))
            )
        )

        link_best_slot = ""
        link_best_score = 0
        for slot, pattern in (
            ("documents_and_checklist", _DOCUMENT_LINK_RE),
            ("tuition_and_fees", _TUITION_LINK_RE),
            ("scholarships_and_funding", _SCHOLARSHIP_LINK_RE),
            ("admissions_and_eligibility", _ADMISSION_LINK_RE),
        ):
            matches = pattern.findall(combined)
            if not matches:
                continue
            score = (
                len(matches) * 2
                + (3 if pattern.search(path_and_query) else 0)
                + (6 if is_child_path else 0)
            )
            if score > link_best_score:
                link_best_score = score
                link_best_slot = slot

        if link_best_slot:
            prev = best.get(link_best_slot)
            if prev is None or link_best_score > prev[0]:
                best[link_best_slot] = (link_best_score, full_url)

    return ProgrammeSublinks(
        tuition_and_fees=best.get("tuition_and_fees", (0, ""))[1],
        admissions_and_eligibility=best.get("admissions_and_eligibility", (0, ""))[1],
        documents_and_checklist=best.get("documents_and_checklist", (0, ""))[1],
        scholarships_and_funding=best.get("scholarships_and_funding", (0, ""))[1],
    )


def _safe_canonical_url(url: str) -> str:
    try:
        return canonicalize_url(url)
    except ValueError:
        return url


def is_page_unchanged(canonical_url: str, html: bytes | str) -> bool:
    """Return True if the latest `OfficialSourceSnapshot` for `canonical_url` already
    carries the identical `content_sha256` or raw `sha256`."""
    norm_url = _safe_canonical_url(canonical_url)
    raw_bytes = html.encode("utf-8") if isinstance(html, str) else html
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    c_digest = content_digest(raw_bytes)
    latest = (
        OfficialSourceSnapshot.objects.filter(source__canonical_url__in=(norm_url, canonical_url))
        .order_by("-retrieved_at")
        .values("sha256", "content_sha256")
        .first()
    )
    if latest is None:
        return False
    if latest["sha256"] == raw_sha:
        return True
    return bool(c_digest and latest["content_sha256"] == c_digest)


def _extract_page_lines(url: str, html: bytes | str) -> tuple[list[Line], str]:
    raw_bytes = html.encode("utf-8") if isinstance(html, str) else html
    structured = list(extract_jsonld_lines(raw_bytes))
    table_dl = list(extract_table_and_dl_lines(raw_bytes))

    fetch_res = FetchResult(
        final_url=url,
        redirects=(),
        content_type="text/html; charset=utf-8",
        body=raw_bytes,
    )
    try:
        text = readable_text(fetch_res, terms=None)
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "programme readable_text degraded for %s (%s: %s)",
            url,
            type(error).__name__,
            error,
        )
        text = ""
    declared_lang = html_lang(raw_bytes)
    if declared_lang or len(text.split()) >= 15:
        lang = detect_language(text, html_lang=declared_lang) or "en"
    else:
        lang = "en"
    prose_page = split_page_lines(text, lang=lang, html=raw_bytes) if text else None

    combined: list[Line] = []
    seen: set[tuple[str, str, str]] = set()
    # Start from in-place enriched prose_page lines (where pipe-tables and <dl> were replaced
    # with 2D coordinate-bound lines), dropping any residual raw pipe-table rows when table_dl
    # extracted structured cells.
    for line in (prose_page.lines if prose_page else ()):
        if table_dl and line.text.startswith("|"):
            continue
        key = (line.text, line.heading, line.header)
        if key not in seen:
            seen.add(key)
            combined.append(line)

    # Append any structured JSON-LD or <table>/<dl> lines that `readable_text` pruned (e.g.
    # key-facts boxes inside `<aside>` or non-main containers).
    for line in (*structured, *table_dl):
        key = (line.text, line.heading, line.header)
        if key in seen:
            continue
        if any(
            line.text in existing.text and (not line.header or line.header in existing.header)
            for existing in combined
        ):
            continue
        seen.add(key)
        combined.append(line)
    return combined, lang


def build_programme_bundle(
    pages: Sequence[tuple[str, bytes | str]],
    *,
    title: str = "",
    base_profile: InstitutionBaseProfile | None = None,
) -> ProgrammeBundle:
    """Assemble a multi-page `ProgrammeBundle` from `(url, html)` pairs and an optional
    `InstitutionBaseProfile`, keeping `Section` within `MAX_SECTION_CHARS`."""
    all_lines: list[Line] = []
    line_sources: list[str] = []
    page_urls: list[str] = []
    detected_lang = "en"
    char_budget = MAX_SECTION_CHARS // 2

    for idx, (url, html) in enumerate(pages):
        page_urls.append(url)
        p_lines, p_lang = _extract_page_lines(url, html)
        if idx == 0 and p_lang:
            detected_lang = p_lang
        path_label = urlsplit(url).path.strip("/") or "home"
        for line in p_lines:
            tagged_heading = (
                f"[{path_label}] {line.heading}".strip()
                if idx > 0 and line.heading
                else (f"[{path_label}]" if idx > 0 else line.heading)
            )
            candidate_line = Line(
                text=line.text,
                heading=tagged_heading[:160],
                header=line.header,
            )
            line_cost = (
                len(candidate_line.text)
                + len(candidate_line.heading)
                + len(candidate_line.header)
                + 40
            )
            if char_budget - line_cost < 0:
                break
            char_budget -= line_cost
            all_lines.append(candidate_line)
            line_sources.append(url)

    if base_profile is not None:
        for b_line, b_src in zip(
            base_profile.base_lines, base_profile.base_line_sources, strict=False
        ):
            line_cost = len(b_line.text) + len(b_line.heading) + len(b_line.header) + 40
            if char_budget - line_cost < 0:
                break
            char_budget -= line_cost
            all_lines.append(b_line)
            line_sources.append(b_src)

    resolved_title = title or (all_lines[0].heading if all_lines else "Programme")
    section = Section(title=resolved_title[:200], lang=detected_lang, lines=tuple(all_lines))
    return ProgrammeBundle(
        section=section,
        line_sources=tuple(line_sources),
        page_urls=tuple(page_urls),
    )


def extract_institution_base_profile(
    domain: str,
    pages: Sequence[tuple[str, bytes | str]],
) -> InstitutionBaseProfile:
    """Build a reusable `InstitutionBaseProfile` once for a university domain from its
    central tuition, admissions, and language pages."""
    bundle = build_programme_bundle(pages, title=f"Institution Base: {domain}")
    tier0 = extract_tier0_programme_facts(bundle)

    tuition_by_cat: dict[str, CostComponentSpec] = {}
    candidates = _candidates_with_header_currency(bundle.section.lines)
    primary_url = bundle.page_urls[0] if bundle.page_urls else f"https://{domain}/"
    for found_amt in candidates.amounts.values():
        amt = found_amt.value
        if amt.low is None or not amt.currency:
            continue
        idx = found_amt.line
        line = bundle.section.lines[idx]
        ctx = f"{line.heading} | {line.header} | {line.text}"
        m_cat = _CATEGORY_REF_RE.search(f"{line.header} {line.text}")
        if not m_cat:
            continue
        cat_key = m_cat.group(1).upper()
        raw_per = _period_from_context(ctx)
        if raw_per == "PER_CREDIT":
            continue
        if raw_per == "PER_ECTS":
            final_amt = amt.low * Decimal(60)
            final_per = "ANNUAL"
        elif raw_per == "SEMESTER":
            final_amt = amt.low * Decimal(2)
            final_per = "ANNUAL"
        else:
            final_amt = amt.low
            final_per = raw_per
        src_url = bundle.line_sources[idx] if idx < len(bundle.line_sources) else primary_url
        quote = locate(amt.text, bundle.section) or Quote(amt.text, f"L{idx}.text")
        spec = CostComponentSpec(
            kind="TUITION",
            amount=final_amt,
            currency=amt.currency,
            period=final_per,
            audience=_amount_audience_on_line(line, amt, from_header=found_amt.from_header),
            quote=quote,
            source_url=src_url,
            from_structured=bool(line.header),
        )
        prev = tuition_by_cat.get(cat_key)
        if prev is None or (spec.audience == "INTERNATIONAL" and prev.audience != "INTERNATIONAL"):
            tuition_by_cat[cat_key] = spec

    default_tuition = next((c for c in tier0.costs if c.kind == "TUITION"), None)
    app_fee = next((c for c in tier0.costs if c.kind == "APPLICATION_FEE"), None)
    lang_reqs = tuple(e for e in tier0.eligibility if e.kind == "LANGUAGE")
    default_dl = next((e for e in tier0.eligibility if e.kind == "DEADLINE"), None)

    return InstitutionBaseProfile(
        domain=domain,
        tuition_by_category=tuition_by_cat,
        default_tuition=default_tuition,
        application_fee=app_fee,
        language_requirements=lang_reqs,
        default_deadline=default_dl,
        document_statements=tier0.statements,
        base_lines=bundle.section.lines,
        base_line_sources=bundle.line_sources,
    )


__all__ = [
    "_extract_page_lines",
    "_safe_canonical_url",
    "build_programme_bundle",
    "classify_programme_sublinks",
    "extract_institution_base_profile",
    "is_page_unchanged",
]
