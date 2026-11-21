"""Home-country macro-fact producer for development scholarships (DAAD A10, System D).

Queries the public World Bank Indicators API v2 (`api.worldbank.org`) by the
student's inferred home country (`ISO 3166-1 alpha-2`) and a domain indicator
matched to their study/research field. Zero student PII leaves the machine:
only the two-letter country code and a fixed World Bank indicator ID are sent,
and responses are cached for 7 days in Django's cache.

Each verified observation is stored on a `NarrativeInput` of kind
`HOME_COUNTRY_CIRCUMSTANCES` with `proposed_by=ENGINE` and a `provenance` dict
carrying `entity` (the country name), `sentence` (the verbatim statement with
year and figure), and `source_url` (the canonical `data.worldbank.org` URL),
so `verify_letter_claims` verifies `SOURCED` home-country claims via
`sourced_claim_matches` using the exact same entity, capitalised-phrase,
number-boundary, and URL checks as `RESEARCH_FIT`.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from uuid import UUID

from django.core.cache import cache

from apps.accounts.models import StudentProfileVersion
from apps.documents.models import NarrativeInput, VerifiedFact
from apps.documents.templatetags.cv_countries import _NAMES as _COUNTRY_NAMES
from apps.research.egress import fetch_data_file
from apps.tenancy.models import Membership

logger = logging.getLogger(__name__)

WORLD_BANK_API_URL = "https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json&mrv=10"
WORLD_BANK_CANONICAL_URL = "https://data.worldbank.org/indicator/{indicator}?locations={country}"
HOME_CONTEXT_CACHE_TTL_SECONDS = 7 * 24 * 3600

DEFAULT_INDICATOR: tuple[str, str] = (
    "GB.XPD.RSDV.GD.ZS",
    "Research and development expenditure (% of GDP)",
)

_DOMAIN_INDICATORS: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "EG.FEC.RNEW.ZS",
        "Renewable energy consumption (% of total final energy consumption)",
        frozenset({
            "energy", "renewable", "solar", "wind", "grid", "power", "photovoltaic",
            "battery", "climate", "emissions", "decarbonization", "decarbonisation",
            "turbine", "hydrogen", "electricity", "thermal",
        }),
    ),
    (
        "ER.H2O.FWTL.ZS",
        "Annual freshwater withdrawals, total (% of internal resources)",
        frozenset({
            "water", "hydrology", "hydrological", "irrigation", "wastewater",
            "sanitation", "groundwater", "flood", "drought", "watershed", "desalination",
            "hydraulic", "river", "aquifer",
        }),
    ),
    (
        "NV.AGR.TOTL.ZS",
        "Agriculture, forestry, and fishing, value added (% of GDP)",
        frozenset({
            "agriculture", "agricultural", "agronomy", "crop", "crops", "soil",
            "livestock", "forestry", "fishery", "fisheries", "food", "horticulture",
            "agroecology", "irrigation", "farming", "veterinary",
        }),
    ),
    (
        "SH.XPD.CHEX.GD.ZS",
        "Current health expenditure (% of GDP)",
        frozenset({
            "health", "healthcare", "medicine", "medical", "clinical", "epidemiology",
            "public", "nursing", "pharmaceutical", "pharmacy", "hospital", "disease",
            "oncology", "biomedical", "immunology", "virology", "nutrition", "maternal",
        }),
    ),
    (
        "SE.XPD.TOTL.GD.ZS",
        "Government expenditure on education, total (% of GDP)",
        frozenset({
            "education", "educational", "teaching", "curriculum", "pedagogy",
            "literacy", "school", "schools", "classroom", "teacher", "tesol",
        }),
    ),
    (
        "IT.NET.USER.ZS",
        "Individuals using the Internet (% of population)",
        frozenset({
            "computer", "computing", "software", "cybersecurity", "telecommunications",
            "telecom", "network", "networks", "internet", "digital", "informatics",
            "cloud", "distributed", "cryptography", "information",
        }),
    ),
    (
        "NE.EXP.GNFS.ZS",
        "Exports of goods and services (% of GDP)",
        frozenset({
            "economics", "economic", "finance", "financial", "trade", "fiscal",
            "monetary", "governance", "policy", "law", "legal", "banking",
            "macroeconomic", "development", "commerce", "customs",
        }),
    ),
    (
        "NV.IND.MANF.ZS",
        "Manufacturing, value added (% of GDP)",
        frozenset({
            "manufacturing", "industrial", "mechanical", "chemical", "materials",
            "metallurgy", "robotics", "automation", "production", "process",
            "structural", "civil", "aerospace", "mechatronics",
        }),
    ),
)

_CODE_BY_NAME: dict[str, str] = {
    name.lower(): code for code, name in _COUNTRY_NAMES.items()
}
_CODE_BY_NAME["uk"] = "GB"
_CODE_BY_NAME["great britain"] = "GB"
_CODE_BY_NAME["usa"] = "US"
_CODE_BY_NAME["united states of america"] = "US"
_WORD_RE = re.compile(r"[a-z]{3,}")


@dataclass(frozen=True)
class HomeContextObservation:
    country_code: str
    country_name: str
    indicator_code: str
    indicator_name: str
    year: int
    value_str: str
    sentence: str
    source_url: str


def _resolve_country_code(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    upper = cleaned.upper()
    if upper == "UK":
        return "GB"
    if len(upper) == 2 and upper in _COUNTRY_NAMES:
        return upper
    return _CODE_BY_NAME.get(cleaned.lower())


def infer_home_country(
    facts: dict[UUID, VerifiedFact],
    *,
    target_country_code: str = "",
    student: Membership | None = None,
) -> tuple[str, str] | None:
    """Resolve `(country_code, country_name)` for the student's home country.

    Checks `IDENTITY` / `PERSONAL` citizenship/nationality facts first, then the
    student's onboarding `StudentProfileVersion.snapshot["nationality"]` when
    `student` is provided, then the modal country across `EDUCATION`,
    `EXPERIENCE` and `RESEARCH` facts outside `target_country_code`. Returns
    `None` when unknown or identical to the destination country.
    """
    target_upper = (target_country_code or "").strip().upper()
    for fact in facts.values():
        if fact.category in (VerifiedFact.Category.IDENTITY, VerifiedFact.Category.PERSONAL):
            for key in ("citizenship", "nationality", "country", "issuing_country"):
                code = _resolve_country_code(fact.payload.get(key))
                if code and code != target_upper:
                    return code, _COUNTRY_NAMES[code]

    if student is not None:
        profile = (
            StudentProfileVersion.objects.filter(student=student)
            .order_by("-version")
            .first()
        )
        if profile is not None and isinstance(profile.snapshot, dict):
            code = _resolve_country_code(profile.snapshot.get("nationality"))
            if code and code != target_upper:
                return code, _COUNTRY_NAMES[code]

    counts: Counter[str] = Counter()
    for category in (
        VerifiedFact.Category.EDUCATION,
        VerifiedFact.Category.EXPERIENCE,
        VerifiedFact.Category.RESEARCH,
    ):
        for fact in facts.values():
            if fact.category != category:
                continue
            code = _resolve_country_code(fact.payload.get("country"))
            if code and code != target_upper:
                counts[code] += 1
        if counts:
            best_code = counts.most_common(1)[0][0]
            return best_code, _COUNTRY_NAMES[best_code]
    return None


def select_indicator_for_context(
    facts: dict[UUID, VerifiedFact],
    *,
    programme_name: str = "",
    storyline_theme: str = "",
) -> tuple[str, str]:
    """Choose the best-fitting `(indicator_code, indicator_name)` from profile keywords."""
    chunks: list[str] = [programme_name, storyline_theme]
    for fact in facts.values():
        if fact.category == VerifiedFact.Category.IDENTITY:
            continue
        for key in (
            "field_of_study",
            "degree_as_awarded",
            "title",
            "summary",
            "description",
            "topic",
        ):
            val = fact.payload.get(key)
            if isinstance(val, str) and val:
                chunks.append(val)
    tokens = set(_WORD_RE.findall(" ".join(chunks).lower()))
    best_code, best_name = DEFAULT_INDICATOR
    best_hits = 0
    for code, name, keywords in _DOMAIN_INDICATORS:
        hits = len(tokens & keywords)
        if hits > best_hits:
            best_hits = hits
            best_code, best_name = code, name
    return best_code, best_name


def _default_fetch_json(url: str) -> object:
    fetched = fetch_data_file(url)
    return json.loads(fetched.body.decode("utf-8"))


def _format_value(value: float) -> str:
    rounded = round(float(value), 2)
    text = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def fetch_world_bank_indicator(
    country_code: str,
    indicator_code: str,
    *,
    fetch_json: Callable[[str], object] | None = None,
) -> HomeContextObservation | None:
    """Fetch and cache the most recent non-null World Bank indicator value."""
    cc = (country_code or "").strip().upper()
    ind = (indicator_code or "").strip()
    if cc not in _COUNTRY_NAMES or not ind:
        return None
    country_name = _COUNTRY_NAMES[cc]
    cache_key = f"research_fit:wb:v1:{cc}:{ind}"
    if fetch_json is None:
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            if cached.get("_empty"):
                return None
            return HomeContextObservation(**cached)

    url = WORLD_BANK_API_URL.format(country=cc, indicator=ind)
    loader = fetch_json or _default_fetch_json
    try:
        payload = loader(url)
    except Exception as exc:
        logger.warning(
            "home_context World Bank fetch degraded for %s/%s (%s): %s",
            cc,
            ind,
            type(exc).__name__,
            exc,
        )
        return None

    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        if fetch_json is None:
            cache.set(cache_key, {"_empty": True}, timeout=HOME_CONTEXT_CACHE_TTL_SECONDS)
        return None

    for row in payload[1]:
        if not isinstance(row, dict):
            continue
        raw_val = row.get("value")
        date_str = str(row.get("date") or "").strip()
        if raw_val is None or not isinstance(raw_val, int | float) or not date_str.isdigit():
            continue
        indicator_obj = row.get("indicator")
        indicator_name = (
            str(indicator_obj.get("value") or "").strip()
            if isinstance(indicator_obj, dict)
            else ""
        )
        if not indicator_name:
            names_map = dict([DEFAULT_INDICATOR, *((c, n) for c, n, _ in _DOMAIN_INDICATORS)])
            indicator_name = names_map.get(ind, ind)
        year = int(date_str)
        value_str = _format_value(float(raw_val))
        source_url = WORLD_BANK_CANONICAL_URL.format(indicator=ind, country=cc)
        sentence = (
            f"According to World Bank data ({year}), {indicator_name} in {country_name} "
            f"stood at {value_str} percent."
        )
        obs = HomeContextObservation(
            country_code=cc,
            country_name=country_name,
            indicator_code=ind,
            indicator_name=indicator_name,
            year=year,
            value_str=value_str,
            sentence=sentence,
            source_url=source_url,
        )
        if fetch_json is None:
            cache.set(cache_key, asdict(obs), timeout=HOME_CONTEXT_CACHE_TTL_SECONDS)
        return obs

    if fetch_json is None:
        cache.set(cache_key, {"_empty": True}, timeout=HOME_CONTEXT_CACHE_TTL_SECONDS)
    return None


def propose_home_country_context(
    *,
    student: Membership,
    facts: dict[UUID, VerifiedFact],
    target_country_code: str = "",
    programme_name: str = "",
    storyline_theme: str = "",
    fetch_json: Callable[[str], object] | None = None,
) -> NarrativeInput | None:
    """Ensure a verified `HOME_COUNTRY_CIRCUMSTANCES` `NarrativeInput` exists for `student`."""
    inferred = infer_home_country(
        facts, target_country_code=target_country_code, student=student
    )
    if inferred is None:
        logger.warning(
            "home_context skipped for student %s: no home country distinct from "
            "target '%s' found in VerifiedFact records",
            student.id,
            target_country_code,
        )
        return None
    country_code, _country_name = inferred
    indicator_code, _indicator_name = select_indicator_for_context(
        facts, programme_name=programme_name, storyline_theme=storyline_theme
    )

    existing = (
        NarrativeInput.objects.filter(
            student=student,
            kind=NarrativeInput.Kind.HOME_COUNTRY_CIRCUMSTANCES,
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
        )
        .order_by("-created_at")
    )
    for row in existing:
        if (
            isinstance(row.provenance, dict)
            and row.provenance.get("country_code") == country_code
            and row.provenance.get("indicator_code") == indicator_code
        ):
            return row

    obs = fetch_world_bank_indicator(country_code, indicator_code, fetch_json=fetch_json)
    if obs is None and indicator_code != DEFAULT_INDICATOR[0]:
        obs = fetch_world_bank_indicator(
            country_code, DEFAULT_INDICATOR[0], fetch_json=fetch_json
        )
    if obs is None:
        return None

    return NarrativeInput.objects.create(
        student=student,
        kind=NarrativeInput.Kind.HOME_COUNTRY_CIRCUMSTANCES,
        text=obs.sentence,
        proposed_by=NarrativeInput.ProposedBy.ENGINE,
        provenance={
            "entity": obs.country_name,
            "sentence": obs.sentence,
            "source_url": obs.source_url,
            "country_code": obs.country_code,
            "indicator_code": obs.indicator_code,
            "indicator_name": obs.indicator_name,
            "year": obs.year,
            "value": obs.value_str,
            "provider": "world_bank",
        },
    )
