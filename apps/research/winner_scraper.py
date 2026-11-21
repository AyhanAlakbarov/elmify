"""3rd-party LinkedIn winner cohort scraper and PII-free cohort aggregator.

Queries a pluggable 3rd-party LinkedIn search/profile provider (`LINKEDIN_WINNER_PROVIDER_URL`
and `LINKEDIN_WINNER_API_KEY`) for past cohorts of a scholarship or degree programme, strips
all personal identifiers (names, LinkedIn URLs, handles, free-text bios) in memory before any
database write, and persists only anonymised aggregate distributions in `WinnerCohortProfile`.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol
from urllib.parse import urlsplit

from apps.funding.models import FundingOpportunity, Institution, Program
from apps.research.models import Organisation, WinnerCohortProfile

logger = logging.getLogger(__name__)

_ISO2_RE = re.compile(r"^[A-Z]{2}$")
_FIELD_CLEAN_RE = re.compile(r"[^a-z0-9+#\s/-]+")
_RESEARCH_SIGNAL_RE = re.compile(
    r"\b(?:publication|published|journal|ieee|acm|springer|elsevier|nature|arxiv|preprint|"
    r"research\s+assistant|research\s+intern|research\s+fellow|visiting\s+researcher|"
    r"co-author|first\s+author|thesis\s+publication)\b",
    re.IGNORECASE,
)


class WinnerProviderError(RuntimeError):
    """Raised when the 3rd-party LinkedIn winner provider fails or returns invalid data."""


@dataclass(frozen=True)
class RawWinnerProfile:
    """In-memory, PII-stripped representation of a single matched winner profile."""

    origin_country: str = ""
    prior_degree_fields: tuple[str, ...] = ()
    prior_degree_level: str = "BACHELOR"
    work_experience_months: int | None = None
    has_research_signal: bool = False


class WinnerSearchProvider(Protocol):
    """Protocol for pluggable 3rd-party LinkedIn winner search providers."""

    provider_name: str

    def search_winners(
        self,
        *,
        query: str,
        target_name: str,
        holder_name: str,
        country_code: str,
        limit: int = 50,
    ) -> Sequence[RawWinnerProfile | Mapping[str, Any]]: ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse all HTTP redirects so bearer tokens and requests never follow off-origin
    or downgrade to cleartext/internal targets."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise urllib.error.HTTPError(
            req.full_url, code, f"redirect refused ({code})", headers, fp
        )


def _validate_https_endpoint(endpoint_url: str) -> None:
    parsed = urlsplit(endpoint_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "Invalid LINKEDIN_WINNER_PROVIDER_URL (must be https without credentials): "
            f"{endpoint_url!r}"
        )
    host = parsed.hostname
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        if host.lower() in {"localhost", "metadata.google.internal"} or host.lower().endswith(
            (".localhost", ".local", ".internal")
        ):
            raise ValueError(f"Unsafe LINKEDIN_WINNER_PROVIDER_URL host: {host!r}") from None
    else:
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        ):
            raise ValueError(f"Unsafe LINKEDIN_WINNER_PROVIDER_URL IP address: {host!r}")


class HttpThirdPartyLinkedInProvider:
    """HTTP client for a configured 3rd-party LinkedIn search/enrichment API."""

    provider_name = "http_linkedin_3p"

    def __init__(
        self,
        *,
        endpoint_url: str,
        api_key: str = "",
        timeout_seconds: float = 15.0,
    ) -> None:
        _validate_https_endpoint(endpoint_url)
        self._endpoint_url = endpoint_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def search_winners(
        self,
        *,
        query: str,
        target_name: str,
        holder_name: str,
        country_code: str,
        limit: int = 50,
    ) -> Sequence[Mapping[str, Any]]:
        _validate_https_endpoint(self._endpoint_url)
        parsed = urlsplit(self._endpoint_url)
        assert parsed.hostname is not None
        try:
            port = parsed.port or 443
            addrs = {str(item[4][0]) for item in socket.getaddrinfo(parsed.hostname, port)}
        except OSError as exc:
            raise WinnerProviderError(
                f"{self.provider_name} DNS resolution failed: {exc}"
            ) from exc
        for raw_ip in addrs:
            ip_obj = ipaddress.ip_address(raw_ip)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                raise WinnerProviderError(
                    f"{self.provider_name} resolved to non-public address {raw_ip}"
                )
        body = json.dumps(
            {
                "query": query,
                "target_name": target_name,
                "holder_name": holder_name,
                "country_code": country_code,
                "limit": max(1, min(int(limit), 100)),
            }
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(
            self._endpoint_url,
            data=body,
            headers=headers,
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirectHandler)
        try:
            with opener.open(req, timeout=self._timeout_seconds) as resp:  # nosec B310
                raw_bytes = resp.read(2 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            raise WinnerProviderError(
                f"{self.provider_name} returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise WinnerProviderError(
                f"{self.provider_name} network error: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise WinnerProviderError(f"{self.provider_name} timed out") from exc

        try:
            decoded = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WinnerProviderError(
                f"{self.provider_name} returned invalid JSON: {exc}"
            ) from exc

        if isinstance(decoded, Mapping):
            results = decoded.get("profiles") or decoded.get("results") or decoded.get("data") or []
        elif isinstance(decoded, list):
            results = decoded
        else:
            raise WinnerProviderError(
                f"{self.provider_name} returned unexpected payload type {type(decoded).__name__}"
            )
        if not isinstance(results, list):
            raise WinnerProviderError(f"{self.provider_name} profiles field is not a list")
        return [item for item in results if isinstance(item, Mapping)]


def default_winner_provider() -> WinnerSearchProvider | None:
    """Build the default 3rd-party LinkedIn provider from environment variables, if configured."""
    url = os.environ.get("LINKEDIN_WINNER_PROVIDER_URL", "").strip()
    if not url:
        return None
    api_key = os.environ.get("LINKEDIN_WINNER_API_KEY", "").strip()
    return HttpThirdPartyLinkedInProvider(endpoint_url=url, api_key=api_key)


def _normalize_degree_level(raw: str) -> str:
    cleaned = raw.strip().upper()
    if cleaned in ("BACHELOR", "MASTER", "PHD", "OTHER"):
        return cleaned
    lower = raw.casefold()
    if any(tok in lower for tok in ("phd", "doctor", "dphil", "dr.")):
        return "PHD"
    if any(tok in lower for tok in ("master", "msc", "m.sc", "ma", "m.a", "meng", "mba", "mres")):
        return "MASTER"
    if any(
        tok in lower for tok in ("bachelor", "bsc", "b.sc", "ba", "b.a", "beng", "btech", "llb")
    ):
        return "BACHELOR"
    return "BACHELOR"


def _normalize_field_token(raw: str) -> str:
    cleaned = _FIELD_CLEAN_RE.sub(" ", raw.casefold())
    collapsed = " ".join(cleaned.split())
    return collapsed[:80]


def parse_raw_winner_profile(item: RawWinnerProfile | Mapping[str, Any]) -> RawWinnerProfile:
    """Strip all PII from a 3rd-party LinkedIn profile record and extract structured signals."""
    if isinstance(item, RawWinnerProfile):
        return item

    raw_cc = str(
        item.get("origin_country")
        or item.get("nationality")
        or item.get("country_code")
        or item.get("country")
        or ""
    ).strip().upper()
    origin_country = raw_cc if _ISO2_RE.match(raw_cc) else ""

    fields: list[str] = []
    raw_fields = item.get("prior_degree_fields")
    if isinstance(raw_fields, Sequence) and not isinstance(raw_fields, (str, bytes)):
        for f in raw_fields:
            norm = _normalize_field_token(str(f))
            if norm and norm not in fields:
                fields.append(norm)

    degree_level = ""
    if item.get("prior_degree_level"):
        degree_level = _normalize_degree_level(str(item["prior_degree_level"]))

    education = item.get("education")
    if isinstance(education, Sequence) and not isinstance(education, (str, bytes)):
        for edu in education:
            if not isinstance(edu, Mapping):
                continue
            field_str = str(edu.get("field_of_study") or edu.get("field") or "")
            norm_field = _normalize_field_token(field_str)
            if norm_field and norm_field not in fields:
                fields.append(norm_field)
            if not degree_level and edu.get("degree_name"):
                degree_level = _normalize_degree_level(str(edu["degree_name"]))

    if not degree_level:
        degree_level = "BACHELOR"

    work_months: int | None = None
    raw_months = item.get("work_experience_months")
    if isinstance(raw_months, (int, float)) and not isinstance(raw_months, bool):
        work_months = max(0, min(int(raw_months), 600))
    else:
        experiences = item.get("experiences")
        if isinstance(experiences, Sequence) and not isinstance(experiences, (str, bytes)):
            total_months = 0
            counted = False
            for exp in experiences:
                if isinstance(exp, Mapping) and isinstance(
                    exp.get("duration_months"), (int, float)
                ):
                    total_months += max(0, int(exp["duration_months"]))
                    counted = True
            if counted:
                work_months = min(total_months, 600)

    has_research = bool(item.get("has_research_signal", False))
    if not has_research:
        pubs = item.get("accomplishment_publications") or item.get("publications")
        if isinstance(pubs, Sequence) and not isinstance(pubs, (str, bytes)) and len(pubs) > 0:
            has_research = True
    if not has_research:
        experiences = item.get("experiences")
        if isinstance(experiences, Sequence) and not isinstance(experiences, (str, bytes)):
            for exp in experiences:
                if isinstance(exp, Mapping):
                    title = str(exp.get("title") or "")
                    if _RESEARCH_SIGNAL_RE.search(title):
                        has_research = True
                        break

    return RawWinnerProfile(
        origin_country=origin_country,
        prior_degree_fields=tuple(fields),
        prior_degree_level=degree_level,
        work_experience_months=work_months,
        has_research_signal=has_research,
    )


def _percentile(sorted_vals: Sequence[int], q: float) -> int | None:
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    if n == 1:
        return int(sorted_vals[0])
    pos = (n - 1) * q
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return int(round(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac))


def aggregate_winner_cohort(
    profiles: Sequence[RawWinnerProfile | Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate matched profiles into PII-free cohort statistics for `WinnerCohortProfile`."""
    parsed = [parse_raw_winner_profile(p) for p in profiles]
    sample_size = len(parsed)
    if sample_size == 0:
        return {
            "sample_size": 0,
            "origin_country_counts": {},
            "prior_degree_fields": {},
            "prior_degree_levels": {},
            "work_experience_months_p25": None,
            "work_experience_months_median": None,
            "work_experience_months_p75": None,
            "research_signal_rate": None,
        }

    country_counts: Counter[str] = Counter()
    field_counts: Counter[str] = Counter()
    level_counts: Counter[str] = Counter()
    work_months: list[int] = []
    research_count = 0

    for prof in parsed:
        if prof.origin_country:
            country_counts[prof.origin_country] += 1
        for f in prof.prior_degree_fields:
            if f:
                field_counts[f] += 1
        if prof.prior_degree_level:
            level_counts[prof.prior_degree_level] += 1
        if prof.work_experience_months is not None:
            work_months.append(prof.work_experience_months)
        if prof.has_research_signal:
            research_count += 1

    work_months.sort()
    rate = (Decimal(research_count) / Decimal(sample_size)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return {
        "sample_size": sample_size,
        "origin_country_counts": dict(sorted(country_counts.items())),
        "prior_degree_fields": dict(sorted(field_counts.items())),
        "prior_degree_levels": dict(sorted(level_counts.items())),
        "work_experience_months_p25": _percentile(work_months, 0.25),
        "work_experience_months_median": _percentile(work_months, 0.50),
        "work_experience_months_p75": _percentile(work_months, 0.75),
        "research_signal_rate": rate,
    }


def _sync_winner_cohort(
    *,
    lookup: dict[str, Any],
    clear_fk: dict[str, None],
    target_kind: str,
    target_label: str,
    target_id: Any,
    target_name: str,
    holder_name: str,
    country_code: str,
    query: str,
    provider: WinnerSearchProvider | None,
    limit: int,
) -> WinnerCohortProfile | None:
    active_provider = provider or default_winner_provider()
    if active_provider is None:
        logger.info(
            "LinkedIn winner provider not configured (LINKEDIN_WINNER_PROVIDER_URL unset); "
            "skipping cohort sync for %s %s",
            target_label,
            target_id,
        )
        return None
    try:
        raw_profiles = active_provider.search_winners(
            query=query,
            target_name=target_name,
            holder_name=holder_name,
            country_code=country_code,
            limit=limit,
        )
    except Exception as exc:
        logger.warning(
            "LinkedIn winner provider %s failed for %s %s (%s): %s",
            getattr(active_provider, "provider_name", "unknown"),
            target_label,
            target_id,
            target_name,
            exc,
        )
        return None
    agg = aggregate_winner_cohort(raw_profiles)
    cohort, _ = WinnerCohortProfile.objects.update_or_create(
        **lookup,
        defaults={
            **clear_fk,
            "target_kind": target_kind,
            "target_name": target_name[:300],
            "holder_name": holder_name[:300],
            "country_code": country_code,
            "source_provider": getattr(active_provider, "provider_name", "")[:64],
            **agg,
        },
    )
    return cohort


def sync_winner_cohort_for_program(
    program: Program,
    *,
    provider: WinnerSearchProvider | None = None,
    limit: int = 50,
) -> WinnerCohortProfile | None:
    """Fetch and upsert the anonymised `WinnerCohortProfile` for a `Program`."""
    holder_name = ""
    if program.institution_id is not None:
        inst_name = (
            Institution.objects.filter(id=program.institution_id)
            .values_list("name", flat=True)
            .first()
        )
        holder_name = str(inst_name or "")
    return _sync_winner_cohort(
        lookup={"program_id": program.id},
        clear_fk={"opportunity_id": None},
        target_kind=WinnerCohortProfile.TargetKind.PROGRAM,
        target_label="program",
        target_id=program.id,
        target_name=program.name,
        holder_name=holder_name,
        country_code=program.country_code,
        query=f'"{program.name}" {holder_name}'.strip(),
        provider=provider,
        limit=limit,
    )


def sync_winner_cohort_for_opportunity(
    opportunity: FundingOpportunity,
    *,
    provider: WinnerSearchProvider | None = None,
    limit: int = 50,
) -> WinnerCohortProfile | None:
    """Fetch and upsert the anonymised `WinnerCohortProfile` for a `FundingOpportunity`."""
    holder_name = str(opportunity.holder_name or "")
    org_cc = ""
    if opportunity.organisation_id is not None:
        org_row = (
            Organisation.objects.filter(id=opportunity.organisation_id)
            .values_list("name", "country_code")
            .first()
        )
        if org_row is not None:
            if not holder_name:
                holder_name = str(org_row[0] or "")
            org_cc = str(org_row[1] or "")
    elif opportunity.institution_id is not None and not holder_name:
        inst_name = (
            Institution.objects.filter(id=opportunity.institution_id)
            .values_list("name", flat=True)
            .first()
        )
        holder_name = str(inst_name or "")
    resolved_cc = str(opportunity.country_code or org_cc or "")
    return _sync_winner_cohort(
        lookup={"opportunity_id": opportunity.id},
        clear_fk={"program_id": None},
        target_kind=WinnerCohortProfile.TargetKind.OPPORTUNITY,
        target_label="opportunity",
        target_id=opportunity.id,
        target_name=opportunity.name,
        holder_name=holder_name,
        country_code=resolved_cc,
        query=f'"{opportunity.name}" {holder_name} scholarship fellow winner'.strip(),
        provider=provider,
        limit=limit,
    )
