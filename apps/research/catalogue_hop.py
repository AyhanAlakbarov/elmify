"""Two-stage hopper for national scholarship databases and hoppable catalogues.

National scholarship and programme databases (`Campus Bourses`, `grants.at`,
`Studyinfo.fi`, `Stipendienlotse`, `EURAXESS`, `AcademicTransfer`, `JASSO`, etc.)
list dozens of external university and foundation awards per directory page.
`official_url_from_catalogue_page` in `harvest.py` extracts a single course link
for 1-to-1 degree detail pages; this module implements the general 1-to-N
hopper (`extract_catalogue_hops` and `CatalogueHopSource`) that extracts all
external official funder and university links from a national database or
catalogue page, filters out commercial aggregators, social links, and PhD-only
paths, and records `POINTER:<catalogue_domain>` entries in the `Organisation`
register.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from .discovery import DiscoveryQuery, LeadSource, ResearchLead, canonicalize_url
from .domains import is_catalogue, is_hoppable_catalogue
from .harvest import anchors
from .hosts import is_hosting_platform, registrable_domain
from .models import Organisation
from .register import record_organisation
from .social_monitor import _MASTERS_RE, _PHD_ONLY_RE, _UNDERGRAD_ONLY_RE, _is_social_host

logger = logging.getLogger(__name__)

_PHD_PATH_RE = re.compile(
    r"(?:^|[^a-z0-9])(phd|doctoral|doctorate|postdoc|bachelor|bachelors|undergraduate|bsc)(?:$|[^a-z0-9])",
    re.I,
)
_DETAIL_PATH_RE = re.compile(
    r"/(?:detail|details|course|courses|program|programme|programmes|programs"
    r"|scholarship|scholarships|bourse|bourses|stipend|formation|view|item|id)/"
    r"|[?&](?:id|course_id|program_id|stipendium)=",
    re.I,
)


def extract_internal_detail_links(
    html: bytes,
    *,
    base_url: str,
    max_links: int = 8,
) -> tuple[str, ...]:
    """Extract same-domain detail-card URLs from a portal search listing for 2-hop resolution."""
    catalogue_domain = registrable_domain(base_url)
    if not catalogue_domain:
        return ()
    try:
        canon_base = canonicalize_url(base_url)
    except ValueError:
        canon_base = base_url
    found: list[str] = []
    for a in anchors(html):
        resolved = urljoin(base_url, a.href).split("#")[0]
        if not resolved.startswith(("http://", "https://")):
            continue
        try:
            canon = canonicalize_url(resolved)
        except ValueError:
            continue
        if canon == canon_base or canon in found:
            continue
        if registrable_domain(canon) != catalogue_domain:
            continue
        if _is_phd_only_target(canon, a.text):
            continue
        if _DETAIL_PATH_RE.search(canon):
            found.append(canon)
            if len(found) >= max_links:
                break
    return tuple(found)


def _is_phd_only_target(url: str, anchor_text: str) -> bool:
    path = urlsplit(url).path
    if _PHD_PATH_RE.search(path) and not _MASTERS_RE.search(path):
        return True
    cleaned = " ".join(anchor_text.split())
    if (
        cleaned
        and (_PHD_ONLY_RE.search(cleaned) or _UNDERGRAD_ONLY_RE.search(cleaned))
        and not _MASTERS_RE.search(cleaned)
    ):
        return True
    return False


def extract_catalogue_hops(
    html: bytes,
    *,
    base_url: str,
    source_type: str = "FUNDER",
    funding_family: str = "GOVERNMENT_SCHOLARSHIP",
    record_pointers: bool = True,
) -> tuple[ResearchLead, ...]:
    """Extract external official funder/institution leads from a catalogue/database HTML page."""
    catalogue_domain = registrable_domain(base_url)
    for_scholarship = source_type == "FUNDER"
    leads: list[ResearchLead] = []
    seen_urls: set[str] = set()

    for a in anchors(html):
        resolved = urljoin(base_url, a.href).split("#")[0]
        if not resolved.startswith(("http://", "https://")):
            continue
        try:
            canon = canonicalize_url(resolved)
        except ValueError:
            continue
        if canon in seen_urls:
            continue

        host = (urlsplit(canon).hostname or "").casefold().strip(".")
        target_domain = registrable_domain(canon)
        if not host or not target_domain:
            continue
        # Must hop off the catalogue's own registrable domain.
        if catalogue_domain and target_domain == catalogue_domain:
            continue
        if _is_social_host(host) or is_hosting_platform(target_domain):
            continue
        if is_hoppable_catalogue(host) or is_catalogue(host, for_scholarship=for_scholarship):
            continue
        if _is_phd_only_target(canon, a.text):
            continue

        seen_urls.add(canon)
        lead = ResearchLead.from_url(
            canon,
            source_type=source_type,
            funding_family=funding_family,
            discovered_by=f"catalogue_hop:{catalogue_domain or 'catalogue'}",
        )
        if not lead.can_support_claim:
            continue
        leads.append(lead)

        if record_pointers and catalogue_domain:
            record_organisation(
                domain=target_domain,
                name=target_domain,
                kind="UNSTATED",
                country_code="",
                status=Organisation.Status.CANDIDATE,
                found_via=f"POINTER:{catalogue_domain}",
            )

    return tuple(leads)


@dataclass(frozen=True)
class CatalogueHopSource:
    """`LeadSource` that fetches directory pages from an inner catalogue/database source
    and yields hopped external official leads."""

    inner: LeadSource
    fetch_html: Callable[[str], object]
    name: str = "catalogue-hop"
    one_programme_per_link: bool = False
    awards_jointly: bool = False
    record_pointers: bool = True

    def _fetch_bytes(self, url: str) -> bytes:
        res = self.fetch_html(url)
        if isinstance(res, bytes):
            return res
        body = getattr(res, "body", b"")
        return body if isinstance(body, bytes) else b""

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        seen: set[str] = set()
        for directory_lead in self.inner.find(query):
            try:
                body = self._fetch_bytes(directory_lead.canonical_url)
            except Exception as exc:
                logger.warning(
                    "catalogue_hop fetch failed for %s: %s",
                    directory_lead.canonical_url,
                    exc,
                )
                continue
            if not body:
                continue
            hop_source_type = (
                "PROGRAM"
                if directory_lead.source_type == "AGGREGATOR"
                else directory_lead.source_type
            )
            hop_family = directory_lead.funding_family or "GOVERNMENT_SCHOLARSHIP"
            hopped = list(
                extract_catalogue_hops(
                    body,
                    base_url=directory_lead.canonical_url,
                    source_type=hop_source_type,
                    funding_family=hop_family,
                    record_pointers=self.record_pointers,
                )
            )
            if not hopped:
                for detail_url in extract_internal_detail_links(
                    body, base_url=directory_lead.canonical_url
                ):
                    try:
                        detail_body = self._fetch_bytes(detail_url)
                    except Exception as exc:
                        logger.debug(
                            "catalogue hop detail fetch failed for %s: %s",
                            detail_url,
                            exc,
                        )
                        continue
                    if not detail_body:
                        continue
                    hopped.extend(
                        extract_catalogue_hops(
                            detail_body,
                            base_url=detail_url,
                            source_type=hop_source_type,
                            funding_family=hop_family,
                            record_pointers=self.record_pointers,
                        )
                    )
            for lead in hopped:
                if lead.canonical_url not in seen:
                    seen.add(lead.canonical_url)
                    yield lead
