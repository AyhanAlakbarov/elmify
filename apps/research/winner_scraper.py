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
    r"(?:\b(?:publication|published|journal|ieee|acm|springer|elsevier|nature|science|wiley|"
    r"mdpi|plos|frontiers|neurips|icml|iclr|cvpr|acl|emnlp|aaai|arxiv|biorxiv|medrxiv|chemrxiv|"
    r"ssrn|preprint|peer[- ]reviewed|research\s+assistant|research\s+intern|research\s+fellow|"
    r"research\s+associate|visiting\s+researcher|postdoc|postdoctoral|doctoral\s+researcher|"
    r"graduate\s+researcher|lab(?:oratory)?\s+assistant|co-author|first\s+author|"
    r"thesis\s+publication|patent|scopus|pubmed|"
    r"wissenschaftliche[rn]?\s+mitarbeiter(?:in)?|forschungsassistent(?:in)?|"
    r"forschungspraktikant(?:in)?|publikation(?:en)?|veröffentlichung|"
    r"assistant(?:e)?\s+de\s+recherche|stagiaire\s+de\s+recherche|chercheur|chercheuse|"
    r"doctorant(?:e)?|allocataire\s+de\s+recherche|ing[eé]nieur\s+de\s+recherche|"
    r"asistente\s+de\s+investigaci[oó]n|investigador(?:a)?|becario\s+de\s+investigaci[oó]n|"
    r"publicaci[oó]n|art[ií]culo\s+cient[ií]fico|bolsista\s+de\s+pesquisa|"
    r"inicia[cç][aã]o\s+cient[ií]fica|pesquisador(?:a)?|assegno\s+di\s+ricerca|"
    r"assegnista\s+di\s+ricerca|ricercatore|ricercatrice|borsista\s+di\s+ricerca|pubblicazione|"
    r"onderzoeksassistent|onderzoeker|promovendus|"
    r"ara[sş]t[ıi]rma\s+g[öo]revlisi|ara[sş]t[ıi]rmac[ıi]|makale|yay[ıi]n|"
    r"elmi\s+i[sş][cç]i|t[əe]dqiqat[cç][ıi]|m[əe]qal[əe]|"
    r"научный\s+сотрудник|младший\s+научный\s+сотрудник|исследователь|"
    r"лаборант[- ]исследователь|публикаци[яи]|стать[яи]|ринц)\b|"
    r"研究員|研究员|研究助手|科研助理|学術論文|学术论文|論文発表|论文发表|筆頭著者|第一作者|"
    r"연구원|연구조교|학술논문|논문)",
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
    gpa: float | None = None
    prior_universities: tuple[str, ...] = ()
    reporting_propensity: float | None = None


@dataclass(frozen=True)
class WinnerArchetype:
    """De-biased Horvitz-Thompson / stabilized Hájek + Empirical-Bayes cohort archetype."""

    sample_size: int
    effective_sample_size: float
    avg_gpa: float | None
    avg_work_months: float | None
    research_share: float | None
    top_prior_universities: tuple[str, ...]
    prior_university_shares: Mapping[str, float] = ()  # type: ignore[assignment]
    origin_country_shares: Mapping[str, float] = ()  # type: ignore[assignment]
    prior_degree_level_shares: Mapping[str, float] = ()  # type: ignore[assignment]
    prior_degree_field_shares: Mapping[str, float] = ()  # type: ignore[assignment]
    shrinkage_factor: float = 0.0
    eb_avg_gpa: float | None = None
    eb_avg_work_months: float | None = None
    eb_research_share: float | None = None


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


_PHD_DEGREE_RE = re.compile(
    r"(?:\b(?:ph\.?d\.?|d\.?phil\.?|doctor(?:ate|ado|at)?|doutorado|dottorato|doktor(?:a|at)?|"
    r"promotion|dr\.\s*(?:rer\.\s*nat|ing|phil|med|jur|oec)|ed\.?d\.?|sc\.?d\.?|d\.?sc\.?|"
    r"eng\.?d\.?|кандидат\s+наук|доктор\s+наук|аспирантура|fəlsəfə\s+doktoru)\b|"
    r"(?:^|\s)dr\.(?:\s|$)|博士|박사)",
    re.IGNORECASE,
)
_MASTER_DEGREE_RE = re.compile(
    r"(?:\b(?:master(?:'s|s)?|m[aá]ster|mast[eè]re|magister|magistra|magistr(?:atura)?|"
    r"m\.?sc\.?|m\.?s\.?|m\.?a\.?|m\.?eng\.?|m\.?b\.?a\.?|m\.?res\.?|m\.?phil\.?|"
    r"ll\.?m\.?|m\.?p\.?a\.?|m\.?p\.?p\.?|m\.?p\.?h\.?|m\.?fin\.?|m\.?f\.?a\.?|m\.?ed\.?|"
    r"laurea\s+magistrale|laurea\s+specialistica|dipl[oô]me\s+d['’]ing[eé]nieur|"
    r"ing[eé]nieur\s+dipl[oô]m[eé]|diplom[- ]ingenieur|dipl\.-ing\.?|diplom[- ]kaufmann|"
    r"diplom[- ]informatiker|diplom[- ]physiker|diplom[- ]chemiker|diplom[- ]mathematiker|"
    r"mestrado|maestr[ií]a|mastergrad|y[uü]ksek\s+lisans|магистр(?:атура)?|магістр|"
    r"dea|dess)\b|修士|硕士|碩士|석사)",
    re.IGNORECASE,
)
_BACHELOR_DEGREE_RE = re.compile(
    r"(?:\b(?:bachelor(?:'s|s)?|b\.?sc\.?|b\.?s\.?|b\.?a\.?|b\.?eng\.?|b\.?tech\.?|"
    r"ll\.?b\.?|b\.?b\.?a\.?|b\.?f\.?a\.?|b\.?ed\.?|licence|licenciatura|"
    r"laurea\s+triennale|laurea\s+di\s+primo\s+livello|bachillerato\s+universitario|"
    r"bacharelado|gradua[cç][aã]o|lisans|bakalavr|бакалавр(?:иат)?)\b|学士|學士|학사)",
    re.IGNORECASE,
)
_DEGREE_RANK: Mapping[str, int] = {
    "OTHER": 0,
    "BACHELOR": 1,
    "MASTER": 2,
    "PHD": 3,
}


def _normalize_degree_level(raw: str) -> str:
    cleaned = raw.strip().upper()
    if cleaned in ("BACHELOR", "MASTER", "PHD", "OTHER"):
        return cleaned
    if _PHD_DEGREE_RE.search(raw):
        return "PHD"
    if _MASTER_DEGREE_RE.search(raw):
        return "MASTER"
    if _BACHELOR_DEGREE_RE.search(raw):
        return "BACHELOR"
    return "BACHELOR"


def _normalize_field_token(raw: str) -> str:
    cleaned = _FIELD_CLEAN_RE.sub(" ", raw.casefold())
    collapsed = " ".join(cleaned.split())
    return collapsed[:80]


def _normalize_gpa(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    val: float | None = None
    if isinstance(raw, (int, float)):
        val = float(raw)
    elif isinstance(raw, str):
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:/\s*(\d+(?:\.\d+)?))?", raw.strip())
        if m:
            num = float(m.group(1))
            denom = float(m.group(2)) if m.group(2) else None
            if denom and denom > 0:
                if num > denom:
                    return None
                return round(max(0.0, min(4.0, (num / denom) * 4.0)), 4)
            val = num
    if val is None or val <= 0.0 or val > 100.0:
        return None
    if val <= 4.0:
        return round(val, 4)
    if val <= 5.0:
        return round((val / 5.0) * 4.0, 4)
    if val <= 10.0:
        return round((val / 10.0) * 4.0, 4)
    return round((val / 100.0) * 4.0, 4)


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

    universities: list[str] = []
    raw_unis = item.get("prior_universities") or item.get("prior_institutions")
    if isinstance(raw_unis, Sequence) and not isinstance(raw_unis, (str, bytes)):
        for u in raw_unis:
            u_clean = " ".join(str(u).split())[:200]
            if u_clean and u_clean not in universities:
                universities.append(u_clean)

    degree_level = ""
    if item.get("prior_degree_level"):
        degree_level = _normalize_degree_level(str(item["prior_degree_level"]))

    raw_gpa = item.get("gpa") if item.get("gpa") is not None else item.get("normalized_gpa")
    gpa = _normalize_gpa(raw_gpa)

    education = item.get("education")
    if isinstance(education, Sequence) and not isinstance(education, (str, bytes)):
        edu_levels: list[str] = []
        for edu in education:
            if not isinstance(edu, Mapping):
                continue
            field_str = str(edu.get("field_of_study") or edu.get("field") or "")
            norm_field = _normalize_field_token(field_str)
            if norm_field and norm_field not in fields:
                fields.append(norm_field)
            raw_school = str(
                edu.get("school") or edu.get("institution") or edu.get("university") or ""
            )
            school_str = " ".join(raw_school.split())[:200]
            if school_str and school_str not in universities:
                universities.append(school_str)
            if edu.get("degree_name"):
                edu_levels.append(_normalize_degree_level(str(edu["degree_name"])))
            if gpa is None and (edu.get("gpa") is not None or edu.get("grade") is not None):
                edu_gpa = edu.get("gpa") if edu.get("gpa") is not None else edu.get("grade")
                gpa = _normalize_gpa(edu_gpa)
        if not degree_level and edu_levels:
            degree_level = max(edu_levels, key=lambda lvl: _DEGREE_RANK.get(lvl, 0))

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
                    desc = str(exp.get("description") or "")
                    if _RESEARCH_SIGNAL_RE.search(f"{title} {desc}"):
                        has_research = True
                        break

    propensity: float | None = None
    raw_prop = item.get("reporting_propensity")
    if raw_prop is None:
        raw_prop = item.get("propensity")
    if isinstance(raw_prop, (int, float)) and not isinstance(raw_prop, bool) and raw_prop > 0:
        propensity = float(raw_prop)

    return RawWinnerProfile(
        origin_country=origin_country,
        prior_degree_fields=tuple(fields),
        prior_degree_level=degree_level,
        work_experience_months=work_months,
        has_research_signal=has_research,
        gpa=gpa,
        prior_universities=tuple(universities),
        reporting_propensity=propensity,
    )


#: Default clipping floor for inverse-propensity weighting (Crump et al. 2009).
MIN_PROPENSITY_FLOOR: float = 0.05

#: Baseline country LinkedIn penetration rates among tertiary-educated cohorts.
_COUNTRY_LINKEDIN_PROPENSITY: Mapping[str, float] = {
    "US": 0.85,
    "GB": 0.82,
    "CA": 0.80,
    "AU": 0.78,
    "NL": 0.82,
    "IE": 0.80,
    "SG": 0.78,
    "SE": 0.75,
    "DK": 0.76,
    "CH": 0.72,
    "FR": 0.70,
    "BE": 0.68,
    "NO": 0.68,
    "FI": 0.66,
    "NZ": 0.72,
    "DE": 0.52,
    "AT": 0.50,
    "IT": 0.58,
    "ES": 0.60,
    "PT": 0.62,
    "PL": 0.52,
    "BR": 0.62,
    "IN": 0.58,
    "TR": 0.50,
    "AZ": 0.35,
    "PK": 0.38,
    "ID": 0.36,
    "VN": 0.30,
    "GE": 0.32,
    "KZ": 0.25,
    "UZ": 0.18,
    "KR": 0.24,
    "JP": 0.15,
    "CN": 0.12,
}
_DEFAULT_COUNTRY_PROPENSITY: float = 0.45

#: Discipline/field self-reporting multipliers on LinkedIn.
_HIGH_LINKEDIN_FIELDS: tuple[str, ...] = (
    "computer science",
    "software",
    "data science",
    "artificial intelligence",
    "machine learning",
    "informatics",
    "information technology",
    "business",
    "finance",
    "economics",
    "management",
    "marketing",
    "mba",
)
_LOW_LINKEDIN_FIELDS: tuple[str, ...] = (
    "history",
    "philosophy",
    "literature",
    "philology",
    "theology",
    "fine arts",
    "music",
    "archaeology",
    "anthropology",
    "agriculture",
    "forestry",
    "veterinary",
    "nursing",
)
_DEGREE_LEVEL_PROPENSITY: Mapping[str, float] = {
    "MASTER": 1.0,
    "BACHELOR": 0.92,
    "PHD": 0.82,
    "OTHER": 0.85,
}


def platform_reporting_propensity(
    profile: RawWinnerProfile,
    *,
    pi_min: float = MIN_PROPENSITY_FLOOR,
    country_propensities: Mapping[str, float] | None = None,
    field_propensities: Mapping[str, float] | None = None,
) -> float:
    """Compute clipped LinkedIn reporting propensity `pi_i = max(pi_min, p_platform(c_i, d_i))`."""
    floor = max(1e-6, min(float(pi_min), 1.0))
    if profile.reporting_propensity is not None and profile.reporting_propensity > 0:
        return max(floor, min(1.0, float(profile.reporting_propensity)))

    c_map = country_propensities or _COUNTRY_LINKEDIN_PROPENSITY
    cc = profile.origin_country.strip().upper()
    p_country = (
        float(c_map.get(cc, _DEFAULT_COUNTRY_PROPENSITY)) if cc else _DEFAULT_COUNTRY_PROPENSITY
    )

    p_field = 0.72
    if profile.prior_degree_fields:
        field_scores: list[float] = []
        for f in profile.prior_degree_fields:
            f_low = f.casefold()
            if field_propensities and f_low in field_propensities:
                field_scores.append(float(field_propensities[f_low]))
            elif any(tok in f_low for tok in _HIGH_LINKEDIN_FIELDS):
                field_scores.append(0.92)
            elif any(tok in f_low for tok in _LOW_LINKEDIN_FIELDS):
                field_scores.append(0.48)
            else:
                field_scores.append(0.72)
        if field_scores:
            p_field = sum(field_scores) / len(field_scores)

    p_level = float(_DEGREE_LEVEL_PROPENSITY.get(profile.prior_degree_level, 0.90))
    raw_pi = p_country * p_field * p_level
    return max(floor, min(1.0, raw_pi))


def kish_effective_sample_size(weights: Sequence[float]) -> float:
    """Kish's effective sample size `n_eff = (sum w_i)^2 / (sum w_i^2)`.

    Satisfies `0 < n_eff <= len(weights)` for any positive weights, with equality
    `n_eff == len(weights)` if and only if all `w_i` are equal.
    """
    pos = [float(w) for w in weights if w > 0]
    if not pos:
        return 0.0
    sum_w = sum(pos)
    sum_w2 = sum(w * w for w in pos)
    if sum_w2 <= 0.0:
        return 0.0
    n_eff = (sum_w * sum_w) / sum_w2
    return min(float(len(pos)), n_eff)


def eb_shrinkage_weight(n_eff: float, kappa: float = 5.0) -> float:
    """Empirical Bayes shrinkage factor `lambda(n_eff) = n_eff / (n_eff + kappa)`."""
    if n_eff <= 0.0:
        return 0.0
    if kappa <= 0.0:
        return 1.0
    return float(n_eff) / (float(n_eff) + float(kappa))


def build_winner_archetype(
    profiles: Sequence[RawWinnerProfile | Mapping[str, Any]],
    *,
    destination_country: str = "",
    pi_min: float = MIN_PROPENSITY_FLOOR,
    country_propensities: Mapping[str, float] | None = None,
    field_propensities: Mapping[str, float] | None = None,
    prior_gpa: float = 3.5,
    prior_work_months: float = 18.0,
    prior_research_share: float = 0.25,
    prior_concentration: float = 0.0,
    eb_kappa: float = 5.0,
    top_k_universities: int = 10,
) -> WinnerArchetype:
    """Aggregate observational LinkedIn winner profiles into a de-biased `WinnerArchetype`
    using stabilized Hájek inverse-propensity weighting (`w_i = 1 / max(pi_min, p_i)`),
    Kish's effective sample size `n_eff = (sum w_i)^2 / sum w_i^2`, and Empirical Bayes."""
    parsed = [parse_raw_winner_profile(p) for p in profiles]
    n = len(parsed)
    if n == 0:
        return WinnerArchetype(
            sample_size=0,
            effective_sample_size=0.0,
            avg_gpa=None,
            avg_work_months=None,
            research_share=None,
            top_prior_universities=(),
            prior_university_shares={},
            origin_country_shares={},
            prior_degree_level_shares={},
            prior_degree_field_shares={},
            shrinkage_factor=0.0,
            eb_avg_gpa=None,
            eb_avg_work_months=None,
            eb_research_share=None,
        )

    weights = [
        1.0
        / platform_reporting_propensity(
            prof,
            pi_min=pi_min,
            country_propensities=country_propensities,
            field_propensities=field_propensities,
        )
        for prof in parsed
    ]
    total_w = sum(weights)
    n_eff = round(kish_effective_sample_size(weights), 4)
    lam_eb = round(eb_shrinkage_weight(n_eff, eb_kappa), 4)

    # 1. GPA (stabilized Hájek IPW over profiles with non-null GPA)
    gpa_pairs = [
        (w, prof.gpa) for w, prof in zip(weights, parsed, strict=True) if prof.gpa is not None
    ]
    hajek_gpa: float | None = None
    eb_gpa: float | None = None
    if gpa_pairs:
        w_gpa = sum(w for w, _ in gpa_pairs)
        raw_hajek_gpa = sum(w * g for w, g in gpa_pairs) / w_gpa
        n_eff_gpa = kish_effective_sample_size([w for w, _ in gpa_pairs])
        lam_gpa = eb_shrinkage_weight(n_eff_gpa, eb_kappa)
        eb_gpa = round(lam_gpa * raw_hajek_gpa + (1.0 - lam_gpa) * prior_gpa, 4)
        if prior_concentration > 0.0:
            lam_active = eb_shrinkage_weight(n_eff_gpa, prior_concentration)
            hajek_gpa = round(lam_active * raw_hajek_gpa + (1.0 - lam_active) * prior_gpa, 4)
        else:
            hajek_gpa = round(raw_hajek_gpa, 4)

    # 2. Work experience months (stabilized Hájek IPW over non-null work_experience_months)
    work_pairs = [
        (w, float(prof.work_experience_months))
        for w, prof in zip(weights, parsed, strict=True)
        if prof.work_experience_months is not None
    ]
    hajek_work: float | None = None
    eb_work: float | None = None
    if work_pairs:
        w_work = sum(w for w, _ in work_pairs)
        raw_hajek_work = sum(w * m for w, m in work_pairs) / w_work
        n_eff_work = kish_effective_sample_size([w for w, _ in work_pairs])
        lam_work = eb_shrinkage_weight(n_eff_work, eb_kappa)
        eb_work = round(lam_work * raw_hajek_work + (1.0 - lam_work) * prior_work_months, 4)
        if prior_concentration > 0.0:
            lam_active = eb_shrinkage_weight(n_eff_work, prior_concentration)
            hajek_work = round(
                lam_active * raw_hajek_work + (1.0 - lam_active) * prior_work_months, 4
            )
        else:
            hajek_work = round(raw_hajek_work, 4)

    # 3. Research signal share (stabilized Hájek IPW over full cohort)
    raw_hajek_res = sum(
        w * (1.0 if prof.has_research_signal else 0.0)
        for w, prof in zip(weights, parsed, strict=True)
    ) / total_w
    eb_res = round(lam_eb * raw_hajek_res + (1.0 - lam_eb) * prior_research_share, 4)
    if prior_concentration > 0.0:
        lam_active = eb_shrinkage_weight(n_eff, prior_concentration)
        hajek_res = round(lam_active * raw_hajek_res + (1.0 - lam_active) * prior_research_share, 4)
    else:
        hajek_res = round(raw_hajek_res, 4)

    # 4. Hájek-weighted categorical shares (prior universities, origin countries, levels, fields)
    uni_weights: dict[str, float] = {}
    country_weights: dict[str, float] = {}
    level_weights: dict[str, float] = {}
    field_weights: dict[str, float] = {}

    for w, prof in zip(weights, parsed, strict=True):
        for uni in prof.prior_universities:
            if uni:
                uni_weights[uni] = uni_weights.get(uni, 0.0) + w
        if prof.origin_country:
            country_weights[prof.origin_country] = (
                country_weights.get(prof.origin_country, 0.0) + w
            )
        if prof.prior_degree_level:
            level_weights[prof.prior_degree_level] = (
                level_weights.get(prof.prior_degree_level, 0.0) + w
            )
        for f in prof.prior_degree_fields:
            if f:
                field_weights[f] = field_weights.get(f, 0.0) + w

    ranked_unis = sorted(uni_weights.items(), key=lambda kv: (-kv[1], kv[0]))
    top_unis = tuple(u for u, _ in ranked_unis[: max(0, int(top_k_universities))])
    uni_shares = {u: round(w / total_w, 4) for u, w in ranked_unis}
    country_shares = {
        c: round(w / total_w, 4)
        for c, w in sorted(country_weights.items(), key=lambda kv: (-kv[1], kv[0]))
    }
    level_shares = {
        lvl: round(w / total_w, 4)
        for lvl, w in sorted(level_weights.items(), key=lambda kv: (-kv[1], kv[0]))
    }
    field_shares = {
        f: round(w / total_w, 4)
        for f, w in sorted(field_weights.items(), key=lambda kv: (-kv[1], kv[0]))
    }

    return WinnerArchetype(
        sample_size=n,
        effective_sample_size=n_eff,
        avg_gpa=hajek_gpa,
        avg_work_months=hajek_work,
        research_share=hajek_res,
        top_prior_universities=top_unis,
        prior_university_shares=uni_shares,
        origin_country_shares=country_shares,
        prior_degree_level_shares=level_shares,
        prior_degree_field_shares=field_shares,
        shrinkage_factor=lam_eb,
        eb_avg_gpa=eb_gpa,
        eb_avg_work_months=eb_work,
        eb_research_share=eb_res,
    )


aggregate_winner_archetype = build_winner_archetype


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


def serialize_winner_archetype(archetype: WinnerArchetype) -> dict[str, Any]:
    """Serialize a `WinnerArchetype` into a JSON-safe mapping for `__archetype__`."""
    return {
        "sample_size": archetype.sample_size,
        "effective_sample_size": archetype.effective_sample_size,
        "shrinkage_factor": archetype.shrinkage_factor,
        "avg_gpa": archetype.avg_gpa,
        "eb_avg_gpa": archetype.eb_avg_gpa,
        "avg_work_months": archetype.avg_work_months,
        "eb_avg_work_months": archetype.eb_avg_work_months,
        "research_share": archetype.research_share,
        "eb_research_share": archetype.eb_research_share,
        "top_prior_universities": list(archetype.top_prior_universities),
        "prior_university_shares": dict(archetype.prior_university_shares),
        "origin_country_shares": dict(archetype.origin_country_shares),
        "prior_degree_level_shares": dict(archetype.prior_degree_level_shares),
        "prior_degree_field_shares": dict(archetype.prior_degree_field_shares),
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
    archetype = aggregate_winner_archetype(
        raw_profiles,
        destination_country=country_code or "",
    )
    prior_levels_with_archetype = dict(agg.get("prior_degree_levels") or {})
    prior_levels_with_archetype["__archetype__"] = serialize_winner_archetype(archetype)
    persisted_agg = {
        **agg,
        "prior_degree_levels": prior_levels_with_archetype,
    }
    cohort, _ = WinnerCohortProfile.objects.update_or_create(
        **lookup,
        defaults={
            **clear_fk,
            "target_kind": target_kind,
            "target_name": target_name[:300],
            "holder_name": holder_name[:300],
            "country_code": country_code,
            "source_provider": getattr(active_provider, "provider_name", "")[:64],
            **persisted_agg,
        },
    )
    cohort.archetype = archetype  # type: ignore[attr-defined]
    logger.info(
        "Synced winner cohort for %s %s "
        "(n=%d, n_eff=%.2f, research_share=%s, eb_research_share=%s)",
        target_label,
        target_id,
        archetype.sample_size,
        archetype.effective_sample_size,
        archetype.research_share,
        archetype.eb_research_share,
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
