"""Where the site hunt looks: the `sitejob` funnel's stages, URLs only, and Part B per page.

Stages, cheapest first (verified-catalog §5.5 step 4; `sitejob.Stage`), each returning URLs and
nothing else -- no vendor's reading of a page is kept, whichever stage found it:

- DOCUMENTS: the links a fetched page prints -- its documents (a rules PDF, an application form)
  and pages whose anchor text or address names a hunted fact. Free: the page is already fetched.
  The only stage whose leads may sit on another domain, because the official site printed them.
- MAP: Firecrawl /map of the start page's own site, searched with the hunted facts' words.
  Bought when the page's own links gave fewer than `CAP` leads.
- GUIDED_MAP: Tavily's guided map of the same site, only when nothing usable was found so far.
- NAVIGATOR: Firecrawl /agent, only when every cheaper stage found nothing, or always under
  `FETCH_NAVIGATOR_POLICY=always`. Its open-web answer is cut to the start page's own domain.

Every lead passes Part B before it is fetched: its registrable domain carries a RECOGNISED
provenance verdict and the URL is the institution's own voice on it (`proven`). A domain never
checked is not followed; it is counted, so the caller can queue its check (2c decision 4). A
failed stage is counted and the next stage still runs: a vendor outage never reads as "this site
has no such page".

Worker-side only, like `entry.read_page` (2c decision 1): every stage bills a vendor, and every
lead it returns is fetched through `fetch_page`, which writes telemetry `runtime_web` cannot touch.
A student-facing view queues the hunt; nothing reachable from `runtime_web` code calls this module.
"""

from __future__ import annotations

import csv
import logging
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from django.conf import settings

from apps.research.domains import verified_kind
from apps.research.fetch.site import FirecrawlSiteError, agent, map_site
from apps.research.fetch.types import FetchedPage
from apps.research.harvest import anchors
from apps.research.hosts import is_hosting_platform, is_institutional_url, registrable_domain
from apps.research.models import Organisation, OrganisationDomain
from apps.research.provenance import RECOGNISED_REASONS, WAITING_REASONS, provenance_of_named
from apps.research.providers.base import ProviderUnavailable
from apps.research.providers.tavily import tavily_guided_map
from apps.research.recognition import government_zone
from apps.research.sitejob import DOCUMENT_SUFFIXES, Stage, navigator_policy

from .awards import fold

logger = logging.getLogger(__name__)

HUNT_TERMS_FILE = Path(__file__).resolve().parents[3] / "docs" / "research" / "hunt-terms.csv"
#: Extra pages read per award per cycle (owner, 2026-10-09); slice 3 counts it across runs.
CAP = 6
#: Words a /map search carries: the vendor ranks by them, so a short, specific list.
MAP_WORDS = 8

#: (site url, words) -> (urls, credits); (site url, instructions, domain) -> (urls, usd);
#: (start url, brief) -> (urls, credits). Each raises on a vendor failure.
MapStage = Callable[[str, Sequence[str]], tuple[Sequence[str], float]]
GuidedStage = Callable[[str, str, str], tuple[Sequence[str], float]]
NavigatorStage = Callable[[str, str], tuple[Sequence[str], float]]
#: What a stage may raise when the vendor, not the site, failed.
VENDOR_FAILURES = (FirecrawlSiteError, ProviderUnavailable)


@dataclass(frozen=True)
class Vendors:
    map: MapStage
    guided: GuidedStage
    navigator: NavigatorStage


@dataclass(frozen=True)
class Lead:
    url: str
    stage: Stage
    #: folded anchor text and address path: what ranking reads; never stored, logged or sent
    words: str
    #: 1 when the lead is a document or a vendor picked it for the facts; 0 when only its words
    #: can make it a lead
    base: int


@cache
def term_rows() -> tuple[tuple[str, str, str], ...]:
    """(field or "*", folded term, language) per row of `docs/research/hunt-terms.csv`."""
    with HUNT_TERMS_FILE.open(encoding="utf-8", newline="") as handle:
        return tuple((r["field"], fold(r["term"]), r["language"]) for r in csv.DictReader(handle))


def _patterns(fields: frozenset[str]) -> list[re.Pattern[str]]:
    """A term matches at a word start; in a script without case (Han, Kana, Hangul) anywhere:
    奨学金募集要項 is one run of letters to `\\w`, and Korean glues particles onto its words."""
    return [re.compile(re.escape(term) if term.upper() == term.lower()
                       else rf"(?<!\w){re.escape(term)}")
            for field, term, _ in term_rows() if field == "*" or field in fields]


def links(page: FetchedPage) -> list[Lead]:
    """DOCUMENTS: every http(s) link the page prints, once, in page order, with its words."""
    out: dict[str, Lead] = {}
    for anchor in anchors(page.body):
        url = urljoin(page.final_url, anchor.href).split("#")[0]
        if not url.startswith(("http://", "https://")) or url in out or url == page.final_url:
            continue
        path = unquote(urlsplit(url).path)
        document = path.casefold().endswith(DOCUMENT_SUFFIXES)
        out[url] = Lead(url, Stage.DOCUMENTS, fold(f"{anchor.text} {path}"), int(document))
    return list(out.values())


def rank(leads: Sequence[Lead], fields: frozenset[str]) -> list[Lead]:
    """The leads worth a fetch, best first: one hit per hunted-fact term in its words, plus its
    base. A lead with neither is never fetched; ties keep the order they were found in."""
    patterns = _patterns(fields)
    scored = [(sum(1 for p in patterns if p.search(lead.words)) + lead.base, n, lead)
              for n, lead in enumerate(leads)]
    return [lead for score, _, lead in sorted(scored, key=lambda s: (-s[0], s[1])) if score]


_FACTS = {"dates": "the application dates and deadline",
          "nationality": "who may apply (the eligible countries or nationalities)",
          "target_level": "the degree level it is for",
          "benefits": "the amount and what it covers"}


def brief(award: str, fields: frozenset[str]) -> str:
    """The guided map's and the navigator's one instruction. The award's name is page text; a
    vendor reads it, and only URLs come back, each proven before it is fetched."""
    facts = [_FACTS[f] for f in sorted(fields) if f in _FACTS]
    if set(fields) - set(_FACTS):
        facts.append("its conditions and details")
    return (f'Find the pages and files on this site that state {", ".join(facts)} for the award '
            f'"{award[:200]}". Return the URLs only. Do not summarise the pages: we read them '
            "ourselves from the official server.")


def proven(url: str) -> bool | None:
    """Part B for one page: True when its domain carries a RECOGNISED verdict and the URL is the
    institution's own voice on it, False when checked and not recognised (or not institutional),
    None when the domain's check has not happened (no verdict, or a WAITING one: not evaluated,
    register not loaded). Reads the gate; never runs a check (2c decision 4)."""
    found = provenance_of_named(url)
    if found is None or found[1] in WAITING_REASONS:
        return None
    return found[1] in RECOGNISED_REASONS


def proven_or_verified_zone(url: str) -> bool | None:
    """Part B with fallback to cited government/academic domain zones and registered closed-list
    bodies when no `ProvenanceVerdict` row has been written yet.

    Preserves `proven()`'s exact verdict whenever a `ProvenanceVerdict` row exists. When `proven()`
    returns `None` (unchecked), admits institutional URLs on cited `GOVERNMENT_ZONES`, registry-
    verified suffixes (`VERIFIED_SECOND_LEVEL`), or `Organisation.Status.REGISTERED` bodies from
    curated closed lists across all 53 target countries.
    """
    verdict = proven(url)
    if verdict is not None:
        return verdict
    domain = registrable_domain(url)
    if not domain or is_hosting_platform(domain) or not is_institutional_url(url, domain):
        return False
    if government_zone(domain) is not None:
        return True
    if verified_kind(domain) in {"INSTITUTION", "NATIONAL_GOVERNMENT", "SUBNATIONAL_GOVERNMENT"}:
        return True
    if OrganisationDomain.objects.filter(
        registrable_domain=domain,
        organisation__status=Organisation.Status.REGISTERED,
    ).exists():
        return True
    return None


def usable(url: str, prove: Callable[[str], bool | None], unproven: set[str]) -> bool:
    """Part B passed; a domain never checked is added to `unproven` and is not usable."""
    domain = registrable_domain(url)
    verdict = prove(url) if domain else False
    if verdict is None:
        unproven.add(domain)
    return bool(verdict)


def page_leads(page: FetchedPage, fields: frozenset[str], *,
               prove: Callable[[str], bool | None], unproven: set[str]) -> list[Lead]:
    """DOCUMENTS for one fetched page: its ranked links that pass Part B, on any domain -- an
    official page printed them (§5.5 step 4, "another official domain counts")."""
    return [lead for lead in rank(links(page), fields) if usable(lead.url, prove, unproven)]


def vendors() -> Vendors:
    """The real stages: Firecrawl /map and /agent on `FIRECRAWL_API_KEY`, Tavily's guided map on
    `SEARCH_API_KEY`. /agent's `maxCredits` is `FETCH_AGENT_MAX_CREDITS` (`site.agent`)."""
    def key() -> str:
        if not settings.FIRECRAWL_API_KEY:
            raise ProviderUnavailable("FIRECRAWL_API_KEY is not set")
        return str(settings.FIRECRAWL_API_KEY)

    def mapped(site: str, words: Sequence[str]) -> tuple[Sequence[str], float]:
        result = map_site(site, api_key=key(), search=words)
        return result.urls, float(result.credits)

    def guided(site: str, instructions: str, domain: str) -> tuple[Sequence[str], float]:
        result = tavily_guided_map(url=site, instructions=instructions, select_domains=[domain])
        return result.urls, result.cost_usd

    def navigated(start: str, prompt: str) -> tuple[Sequence[str], float]:
        result = agent(api_key=key(), urls=[start], prompt=prompt)
        return tuple(url for url, _ in result.leads), float(result.credits)

    return Vendors(mapped, guided, navigated)


def map_words(fields: frozenset[str], lang: str) -> list[str]:
    """The /map search words: the site's own language first, then English; the hunted facts'
    words before the general ones. Composed again (NFC), because folding splits Hangul into
    jamo the vendor's index would never match."""
    rows = sorted(term_rows(), key=lambda r: (r[2] != lang, r[0] == "*"))
    return [unicodedata.normalize("NFC", term) for field, term, language in rows
            if (field == "*" or field in fields) and language in {"en", lang}][:MAP_WORDS]


def find_leads(start: FetchedPage, award: str, fields: frozenset[str], *, lang: str,
               vendors: Vendors, spend: dict[str, float], unproven: set[str],
               prove: Callable[[str], bool | None] = proven) -> list[Lead]:
    """The proven leads for one award's hunted fields: stage by stage in the order bought,
    cheapest first, and best first within each stage.
    `spend` gains each stage's vendor figure (`map_credits`, `guided_usd`,
    `navigator_credits`) or a `<stage>_failed` count; `unproven` gains each domain never
    checked. An unproven start page hunts nowhere: its site is what every lead is proven from."""
    site = registrable_domain(start.final_url)

    def ok(url: str) -> bool:
        """A vendor's lead: on the start page's own site and proven there."""
        return registrable_domain(url) == site and usable(url, prove, unproven)

    if not ok(start.final_url):
        return []
    found = page_leads(start, fields, prove=prove, unproven=unproven)

    def buy(name: str, stage: Stage, unit: str, run: Callable[[], tuple[Sequence[str], float]],
            base: int) -> None:
        try:
            urls, cost = run()
        except VENDOR_FAILURES as error:
            logger.warning("hunt: %s failed (%s)", name, type(error).__name__)
            spend[f"{name}_failed"] = spend.get(f"{name}_failed", 0) + 1
            billed = getattr(error, "credits", 0)  # spend made before the failure, when known
            if billed:
                spend[f"{name}_{unit}"] = spend.get(f"{name}_{unit}", 0) + billed
            return
        spend[f"{name}_{unit}"] = spend.get(f"{name}_{unit}", 0) + cost
        seen = {lead.url for lead in found}
        leads = [Lead(url, stage, fold(unquote(urlsplit(url).path)), base)
                 for url in dict.fromkeys(u.split("#")[0] for u in urls)
                 if url not in seen and url != start.final_url]
        found.extend(lead for lead in rank(leads, fields) if ok(lead.url))

    words = map_words(fields, lang)
    if len(found) < CAP:
        buy("map", Stage.MAP, "credits", lambda: vendors.map(start.final_url, words), 0)
    if not found:
        buy("guided", Stage.GUIDED_MAP, "usd",
            lambda: vendors.guided(start.final_url, brief(award, fields), site), 1)
    if not found or navigator_policy() == "always":
        buy("navigator", Stage.NAVIGATOR, "credits",
            lambda: vendors.navigator(start.final_url, brief(award, fields)), 1)
    return found
