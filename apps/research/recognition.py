"""Who may vouch for a body, read as data (institution provenance gate spec
§5.1, §5.2, §5.7, §13.8).

Every route here binds a body to a domain through a list row a person reviewed,
a register's own website field, or an identifier -- never a name. Which lists
count, and in which role, is `docs/research/provenance-sources.csv`: one
reviewed row per source, keyed by its `closed-lists.csv` slug, so adding a
country or a list is a one-row diff and never a per-school step.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import lxml.etree
import lxml.html
from django.db import transaction

from .closed_lists import (
    DATA_DIR,
    REGISTRY,
    ListFileError,
    ListReport,
    ListRow,
    _rows_of,
    read_registry,
    record_list,
)
from .egress import (
    MAX_RESPONSE_BYTES,
    FetchResult,
    SourceBlocked,
    UnsafeTarget,
    fetch_data_file,
)
from .fetch import fetch_page
from .fetch.types import FetchedPage, Outcome
from .harvest import page_text
from .hosts import is_hosting_platform, registrable_domain
from .models import (
    ClosedList,
    Organisation,
    OrganisationDomain,
    RegisterEntry,
    RegisterEntryPartner,
    ResolvedVia,
)
from .names import tokens
from .provenance import Reason, Recognition
from .ror import RorFacts
from .services import DomainBusy, acquire_domain_lease
from .snapshot import ObjectStore
from .storage import S3ObjectStore

logger = logging.getLogger(__name__)

SOURCES = DATA_DIR / "provenance-sources.csv"
_SOURCE_COLUMNS = (
    "slug", "role", "enic_naric_page", "named_by_hand_because", "data_url", "format",
    "encoding", "records_path", "name_field", "website_field", "id_field", "id_scheme",
    "list_anchor", "max_bytes",
)
ROLES = (Reason.REGISTER, Reason.CURATED_LIST, Reason.FUNDER_LIST)
FORMATS = ("tsv", "json_list", "html_list", "html_records")
_UNBOUND = ("CONFLICT", "NO_KEY")

Fetch = Callable[..., FetchedPage]


class SourceFileError(ListFileError):
    """A provenance-sources row that does not say what the loader needs."""


@dataclass(frozen=True)
class ProvenanceSource:
    slug: str
    role: str
    enic_naric_page: str = ""
    named_by_hand_because: str = ""
    data_url: str = ""
    format: str = ""
    encoding: str = "utf-8"
    records_path: str = ""
    name_field: str = ""
    website_field: str = ""
    id_field: str = ""
    id_scheme: str = ""
    list_anchor: str = ""
    max_bytes: int = MAX_RESPONSE_BYTES


def read_sources(path: Path = SOURCES, registry: Path = REGISTRY) -> tuple[ProvenanceSource, ...]:
    listed_at = {str(spec["slug"]): str(spec["source_url"]) for spec in read_registry(registry)}
    sources: list[ProvenanceSource] = []
    for where, raw in _rows_of(path, _SOURCE_COLUMNS):
        row = {key: value.strip() for key, value in raw.items()}
        if row["slug"] not in listed_at:
            raise SourceFileError(f"{where}: {row['slug']!r} has no row in closed-lists.csv")
        if row["role"] not in ROLES:
            raise SourceFileError(f"{where}: role {row['role']!r} is not one of {ROLES}")
        if row["role"] == Reason.REGISTER:
            if bool(row["enic_naric_page"]) == bool(row["named_by_hand_because"]):
                # A hand reason is for a register with no ENIC-NARIC page; on a
                # row that has one it would read as leave to skip m13, which
                # load_register instead proves through the downloads page.
                raise SourceFileError(
                    f"{where}: a register names its ENIC-NARIC page or says why it is "
                    "named by hand, never both (spec §5.1: ENIC-NARIC is the root of trust)"
                )
            if not row["data_url"].startswith("https://"):
                raise SourceFileError(f"{where}: data_url must be https")
            if row["format"] not in FORMATS:
                raise SourceFileError(f"{where}: format {row['format']!r} is not {FORMATS}")
            if row["format"] == "html_list" and not row["list_anchor"]:
                raise SourceFileError(f"{where}: an html_list needs a list_anchor")
            if row["format"] == "html_records" and not row["records_path"]:
                raise SourceFileError(f"{where}: html_records needs a records_path XPath")
            if row["format"] != "html_list" and not (row["name_field"] and row["website_field"]):
                raise SourceFileError(f"{where}: name_field and website_field are required")
        sources.append(
            ProvenanceSource(
                slug=row["slug"], role=row["role"], enic_naric_page=row["enic_naric_page"],
                named_by_hand_because=row["named_by_hand_because"], data_url=row["data_url"],
                format=row["format"], encoding=row["encoding"] or "utf-8",
                records_path=row["records_path"], name_field=row["name_field"],
                website_field=row["website_field"], id_field=row["id_field"],
                id_scheme=row["id_scheme"], list_anchor=row["list_anchor"],
                max_bytes=int(row["max_bytes"]) if row["max_bytes"] else MAX_RESPONSE_BYTES,
            )
        )
    return tuple(sources)


def readable_page(page: FetchedPage) -> bool:
    """A page with bytes a caller may read. UNCHANGED carries its body too
    (fetch/__init__.py, `_CARRIES_BYTES`). Not `fetch.types.usable`, which asks
    whether raw vendor bytes are a document at all."""
    return bool(page.body) and (page.ok or page.outcome == Outcome.UNCHANGED)


def list_recognitions(
    organisation: Organisation,
    sources: tuple[ProvenanceSource, ...] | None = None,
    *,
    domain: str = "",
    require_register_origin: bool = False,
) -> tuple[tuple[Recognition, ...], bool]:
    """(recognitions from list rows bound to this body's OWN domains, whether a
    reviewed row names it but its origin is not verified yet -> unmapped_list_row).

    Only rows the list itself bound (`resolved_via=LISTED`): the resolver binds
    rows by name, and a name-bound row must never admit. A row whose website is
    another domain recognises the body of THAT domain, never this one.
    `domain` narrows both answers to that one of the body's domains -- the
    verdict is per (body, domain), so a row for domain B says nothing of A.
    """
    sources = sources if sources is not None else read_sources()
    by_slug = {source.slug: source for source in sources}
    lists = ClosedList.objects.in_bulk(list(by_slug))
    own = [domain] if domain else list(
        OrganisationDomain.objects.filter(organisation=organisation).values_list(
            "registrable_domain", flat=True
        )
    )
    found: list[Recognition] = []
    unverified = False
    entries = RegisterEntry.objects.filter(
        organisation=organisation, register__in=list(by_slug),
        resolution=RegisterEntry.Resolution.RESOLVED, resolved_via=ResolvedVia.LISTED,
        website_domain__in=own,
    ).order_by("register", "external_key")
    for entry in entries:
        source = by_slug[entry.register]
        spec = lists.get(entry.register)
        if source.role == Reason.REGISTER and not (
            spec and spec.loaded_at and entry.last_seen >= spec.loaded_at
        ):
            # load_register stamps a row's last_seen and the list's loaded_at
            # with one `now`: an older row is one the last load did not see,
            # i.e. an institution the register has since delisted.
            continue
        verified = entry.origin_verified_domain == entry.website_domain
        # A register row proves nothing until its printed website names it
        # (spec 11.1, P1): `check_body` asks for that; the register loaders do not.
        needs_origin = source.role == Reason.CURATED_LIST or (
            require_register_origin and source.role == Reason.REGISTER
        )
        if needs_origin and not verified:
            unverified = True
            continue
        found.append(
            Recognition(
                reason=source.role, bound_domain=entry.website_domain, source_slug=entry.register,
                source_url=spec.source_url if spec else "",
                list_date=spec.verified_on.isoformat() if spec else "",
                country_code=spec.country_code if spec else "",
                identifier=(source.id_scheme, entry.external_key) if source.id_scheme else None,
            )
        )
    funder_slugs = [source.slug for source in sources if source.role == Reason.FUNDER_LIST]
    partners = (
        RegisterEntryPartner.objects.filter(
            organisation=organisation, entry__register__in=funder_slugs, listed_domain__in=own,
        )
        .exclude(disposition__in=_UNBOUND)
        .select_related("entry")
        .order_by("entry__register", "listed_identifier")
    )
    for partner in partners:
        spec = lists.get(partner.entry.register)
        found.append(
            Recognition(
                reason=Reason.FUNDER_LIST, bound_domain=partner.listed_domain,
                source_slug=partner.entry.register,
                source_url=spec.source_url if spec else "",
                list_date=spec.verified_on.isoformat() if spec else "",
                identifier=("EACEA_PIC", partner.listed_identifier),
            )
        )
    return tuple(found), unverified


#: Government-only zones, each with the registry policy that restricts it
#: (spec §5.7), every page re-read 2026-09-27. A `gov.*` pattern alone is never
#: proof; a zone is added only with its citation. Pinned by
#: test_recognition_lists.py. What each page says:
#: - gov: ".gov domains ... are only available to U.S.-based government organizations";
#: - gov.tr: TRABİS "belgeli" rules, "gov.tr Kamu kurum ve kuruluşlarına tahsis edilir";
#: - go.jp: JPRS, "GO.JP Japanese government authorities, research institutes
#:   under Japanese authority's jurisdiction, and government-affiliated corporations";
#: - go.kr: KISA, "go Administrative agencies or legislative/judicial agencies";
#: - europa.eu: a single-owner domain -- the Commission's legal notice names
#:   "the European Union's websites within the europa.eu domain";
#: - auswaertiges-amt.de: a single-owner domain -- its Impressum names the
#:   Auswärtiges Amt as publisher;
#: - gov.az: Special State Protection Service, "GOV.AZ (Government.az) is a
#:   special domain zone reserved for the naming of Internet information
#:   resources of state bodies";
#: - gov.ge: "can only be registered under the name of state entities, or local
#:   self-government units or organizations, legal entities under public law";
#: - gov.uk: "Only the following organisations can apply for a .gov.uk domain name";
#: - gov.sa: "Dedicated only for governmental entities in the Kingdom of Saudi Arabia";
#: - gov.qa: CRA, "For Qatar governmental organizations";
#: - gov.sg: "Only government bodies or members of the Singapore Government are eligible";
#: - gov.cn: CNNIC rules (CAC), "申请者应为行政机关法人";
#: - gov.vn: VNNIC, "Cơ quan nhà nước ở trung ương và địa phương";
#: - gov.za: SITA, "Any South African government department";
#: - gov.it: Registro .it, "solo da quelle Pubbliche Amministrazioni".
#: Measured 2026-10-03 (.context/research/2026-10-03-government-zone-citations.md
#: on claude/verified-catalog-design). Not added, and why: gov.au and gov.rs (the
#: policy page timed out / returned 403 on the 2026-10-04 re-check), gov.kw (a
#: description, no rule), gov.bh ("semi-Government"), gov.ru (no published rule),
#: gov.et ("should"), gc.ca (no exclusivity sentence); gob.mx, gov.eg, gov.ng,
#: gov.pl, gov.br and gov.kz admit state companies or rest on repealed text.
GOVERNMENT_ZONES: tuple[tuple[str, str], ...] = (
    ("gov", "https://get.gov/domains/eligibility/"),
    ("gov.tr", "https://www.trabis.gov.tr/content/Belgeli"),
    ("go.jp", "https://jprs.co.jp/en/jpdomain.html"),
    (
        "go.kr",
        "https://xn--3e0bx5euxnjje69i70af08bea817g.xn--3e0b707e/jsp/eng/domain/kr/qualification.jsp",
    ),
    ("europa.eu", "https://commission.europa.eu/legal-notice_en"),
    ("auswaertiges-amt.de", "https://www.auswaertiges-amt.de/de/impressum"),
    ("gov.az", "https://scis.gov.az/en/pages/view/dns-xidmeti"),
    ("gov.ge", "https://nic.ge/en/domains/what-is-a-domain-name"),
    ("gov.uk", "https://www.gov.uk/guidance/check-if-your-organisation-can-get-a-govuk-domain-name"),
    ("gov.sa", "https://nic.sa/en/help/regulation/"),
    ("gov.qa", "https://www.cra.gov.qa/en/Regulatory-Framework/Domain-Management/Registrants"),
    ("gov.sg", "https://www.sgnic.sg/domain-registration/sg-categories-rules"),
    ("gov.cn", "https://www.cac.gov.cn/2012-05/28/c_126540129.htm"),
    ("gov.vn", "https://archive.vnnic.vn/tenmien/chinhsach/quy-trinh-dang-ky-ten-mien-duoi-govvn"),
    ("gov.za", "http://dnsadmin.gov.za/faq.htm"),
    ("gov.it", "https://www.nic.it/it/domini-gov-it"),
)


def government_zone(domain: str) -> Recognition | None:
    for zone, citation in GOVERNMENT_ZONES:
        if domain == zone or domain.endswith(f".{zone}"):
            return Recognition(
                reason=Reason.GOVERNMENT_ZONE, bound_domain=domain,
                source_slug=f"zone:{zone}", source_url=citation,
            )
    return None


def name_variants(name: str) -> tuple[str, ...]:
    """The row's name and its bracketed or slashed alternative, casefolded.
    Used only to confirm a website a person already mapped (spec §13.8), never
    to find one."""
    base, _, bracket = name.partition(" (")
    parts = [base, bracket.rstrip(")"), *base.split(" / ")[1:]]
    return tuple(
        dict.fromkeys(" ".join(part.split()).casefold() for part in parts if len(part.strip()) >= 4)
    )


def _origin_urls(entry: RegisterEntry) -> tuple[str, ...]:
    """The website the list printed, then its root-domain / `www.` counterpart."""
    domain = entry.website_domain
    printed = entry.website_url or f"https://{domain}/"
    counterpart = (
        f"https://www.{domain}/" if urlsplit(printed).hostname == domain else f"https://{domain}/"
    )
    return tuple(dict.fromkeys((printed, counterpart)))


def _names_any(text: str, names: Iterable[str], domain: str) -> bool:
    """Whether any of `names` appears in `text` as whole folded words. Every
    token that carries `domain` is blanked first: a parked "daad.de is for
    sale" prints the domain, never the institution."""
    text = re.sub(rf"\S*{re.escape(domain)}\S*", " ", text, flags=re.I)
    words = f" {' '.join(tokens(text))} "
    for name in names:
        for variant in name_variants(name):
            if domain in variant:
                continue
            folded = " ".join(tokens(variant))
            if folded and f" {folded} " in words:
                return True
    return False


def names_institution(entry: RegisterEntry, body: bytes) -> bool:
    """Whether the page names the row, as whole folded words."""
    return _names_any(page_text(body), [entry.name], entry.website_domain)


def _fetch_first_readable(urls: Iterable[str], fetch: Fetch) -> FetchedPage:
    """The first readable fetch of `urls`, else the last one tried."""
    for url in urls:
        fetched = fetch(url, purpose="provenance")
        if readable_page(fetched):
            break
    return fetched


def verify_origin(
    entry: RegisterEntry, *, now: datetime, fetch: Fetch | None = None,
    identity_only: bool = False,
) -> str:
    """Fetch the printed website (its counterpart only if that is unreadable)
    and confirm it names the institution. Returns "verified" or why not; only
    "verified" writes anything. `identity_only` narrows the name check to where a
    site names itself (header, title), as spec 4.1 requires of a register row."""
    fetch = fetch or fetch_page
    urls = _origin_urls(entry)
    if registrable_domain(urls[0]) != entry.website_domain:
        return f"printed website {urls[0]} is not on the listed domain"
    fetched = _fetch_first_readable(urls, fetch)
    if not readable_page(fetched):
        return f"not fetched ({fetched.outcome}: {fetched.reason})"
    if registrable_domain(fetched.final_url) != entry.website_domain:
        return f"redirected off the listed domain to {fetched.final_url}"
    named = (
        names_on_identity([entry.name, *entry.names], fetched.body, domain=entry.website_domain)
        if identity_only else names_institution(entry, fetched.body)
    )
    if not named:
        return "the page does not name the institution"
    entry.origin_verified_domain = entry.website_domain
    entry.origin_verified_at = now
    entry.save(update_fields=["origin_verified_domain", "origin_verified_at"])
    return "verified"


def verify_list_origins(
    slugs: Iterable[str], *, now: datetime, fetch: Fetch | None = None
) -> list[tuple[str, str, str]]:
    """(list, row key, outcome) for every list-bound row of `slugs`."""
    results: list[tuple[str, str, str]] = []
    entries = (
        RegisterEntry.objects.filter(
            register__in=list(slugs), resolution=RegisterEntry.Resolution.RESOLVED,
            resolved_via=ResolvedVia.LISTED,
        )
        .exclude(website_domain="")
        # A REJECTED body is never admitted; verifying its row only spends credits.
        .exclude(organisation__status=Organisation.Status.REJECTED)
        .order_by("register", "external_key")
    )
    for entry in entries:
        if entry.origin_verified_domain == entry.website_domain:
            results.append((entry.register, entry.external_key, "already verified"))
            continue
        outcome = verify_origin(entry, now=now, fetch=fetch)
        if outcome != "verified":
            logger.warning("origin of %s %s not verified: %s", entry.register,
                           entry.external_key, outcome)
        results.append((entry.register, entry.external_key, outcome))
    return results


def verify_register_origins(
    organisation: Organisation,
    domain: str,
    sources: tuple[ProvenanceSource, ...],
    *,
    now: datetime,
    fetch: Fetch,
    tried: set[object],
) -> None:
    """Run verify_origin on this body's register rows for `domain` that are not
    verified yet, each at most once per check (`tried` is the check's memo)."""
    if is_hosting_platform(domain) or organisation.status == Organisation.Status.REJECTED:
        return  # can never admit; spend no fetch
    slugs = [source.slug for source in sources if source.role == Reason.REGISTER]
    entries = RegisterEntry.objects.filter(
        organisation=organisation, register__in=slugs, website_domain=domain,
        resolution=RegisterEntry.Resolution.RESOLVED, resolved_via=ResolvedVia.LISTED,
    ).exclude(origin_verified_domain=domain)
    for entry in entries:
        if entry.pk in tried:
            continue
        tried.add(entry.pk)
        outcome = verify_origin(entry, now=now, fetch=fetch, identity_only=True)
        if outcome != "verified":
            logger.warning("register origin of %s %s not verified: %s",
                           entry.register, entry.external_key, outcome)


#: Where a site names itself (spec §4.1 step 3). The body text is deliberately
#: not read: a regulator's homepage names the bodies it regulates (yok.gov.tr
#: lists universities), and those names must never make it their site. A
#: header or footer is the site's own only outside article, aside, main, nav
#: and section (HTML-AAM's banner / contentinfo rule).
_SECTIONING = (
    "ancestor::article or ancestor::aside or ancestor::main or ancestor::nav or ancestor::section"
)
_PAGE_LEVEL = f"[not({_SECTIONING})]"
_IDENTITY_REGIONS = (
    "//title[not(ancestor::*[local-name()='svg'])]",
    f"//header{_PAGE_LEVEL}", f"//footer{_PAGE_LEVEL}",
    f"//*[@role='banner']{_PAGE_LEVEL}", f"//*[@role='contentinfo']{_PAGE_LEVEL}",
)
_IDENTITY_META = "//meta[@property='og:site_name' or @name='application-name']/@content"
_LOGO_IMG = (
    "//img[contains(translate(concat(@class, ' ', @id, ' ', @src), 'LOGO', 'logo'), 'logo')]"
)
_IN_REGION = (
    f"[ancestor::*[@role='banner' or @role='contentinfo']{_PAGE_LEVEL}"
    f" or ancestor::header{_PAGE_LEVEL} or ancestor::footer{_PAGE_LEVEL}]"
)


def _parse_html(body: bytes) -> Any:
    """UTF-8 first, as reader._document does: lxml assumes Latin-1 for bytes
    with no charset, and vendor bodies are UTF-8 (measured, PR #155)."""
    try:
        return lxml.html.document_fromstring(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return lxml.html.document_fromstring(body)


def _links_to_root(img: Any, domain: str) -> bool:
    """Whether the logo sits in a link to the site's own root."""
    for anchor in img.xpath("ancestor::a[@href]"):
        href = anchor.get("href", "").strip()
        if href in ("/", "./"):
            return True
        try:
            parts = urlsplit(href)
        except ValueError:  # hostile href, e.g. "http://["
            continue
        if domain and parts.hostname in (domain, f"www.{domain}") and parts.path in ("", "/"):
            return True
    return False


def identity_text(body: bytes, *, domain: str = "") -> str:
    """The text of the parts of a page where a site names itself, joined."""
    try:
        doc = _parse_html(body)
    except (lxml.etree.ParserError, ValueError):
        return ""
    parts: list[str] = [
        el.text_content() for xpath in _IDENTITY_REGIONS for el in doc.xpath(xpath)
    ]
    parts.extend(str(value) for value in doc.xpath(_IDENTITY_META))
    # A logo names the site only in a site-level region or a link to the root;
    # a partner's logo in the page body names the partner.
    parts.extend(str(v) for v in doc.xpath(f"{_LOGO_IMG}{_IN_REGION}/@alt"))
    for img in doc.xpath(f"{_LOGO_IMG}[@alt]"):
        if _links_to_root(img, domain):
            parts.append(img.get("alt"))
    return " ".join(parts)


def names_on_identity(names: Iterable[str], body: bytes, *, domain: str) -> bool:
    """Whether any of `names` appears, as whole folded words, where the page
    names itself. Tokens carrying `domain` are blanked first: a parked page
    prints the domain, never the body (as names_institution does)."""
    return _names_any(identity_text(body, domain=domain), names, domain)


def body_names(organisation: Organisation) -> tuple[str, ...]:
    """Every name the platform holds for a body: its own label and the name on
    each register or curated-list row bound to it (local-language names arrive
    this way). A funder list's row names a project, not its coordinator, so it
    never counts (verified-catalog §3.2)."""
    naming = [s.slug for s in read_sources() if s.role in (Reason.REGISTER, Reason.CURATED_LIST)]
    listed = RegisterEntry.objects.filter(
        organisation=organisation, register__in=naming
    ).values_list("name", flat=True)
    return tuple(dict.fromkeys((organisation.name, *listed)))


def site_identity(
    organisation: Organisation, domain: str, *, fetch: Fetch, names: Iterable[str] = ()
) -> str:
    """Fetch `domain`'s homepage (its `www.` counterpart only if unreadable) and
    confirm it names the body where a site names itself. "verified",
    "lookup_failed", or why not; it writes nothing."""
    fetched = _fetch_first_readable((f"https://{domain}/", f"https://www.{domain}/"), fetch)
    if not readable_page(fetched):
        return "lookup_failed"
    if registrable_domain(fetched.final_url) != domain:
        return f"redirected off the domain to {fetched.final_url}"
    if not names_on_identity((*body_names(organisation), *names), fetched.body, domain=domain):
        return "the homepage does not name the body"
    return "verified"


class RegisterShape(ValueError):
    """A register that no longer reads the way its row says. Loud: loading
    nothing would read as every institution in the country absent."""


class RegisterNotVouched(RuntimeError):
    """Not linked from its ENIC-NARIC page, or its file is off the vouched site.

    Never raised for reuse terms: owner decision 2026-09-27, "allow everything,
    as we are using external services". `ClosedList.reuse_terms` is recorded
    information, not a gate."""


class RegisterUnreachable(RuntimeError):
    pass


@dataclass(frozen=True)
class RegisterRow:
    key: str
    name: str
    website: str


_ENIC_HEADING = "Recognised Higher Education Institutions"
LOAD_LEASE = timedelta(minutes=30)
FetchFile = Callable[..., FetchResult]


def enic_register_links(body: bytes) -> tuple[str, ...]:
    """Links in ENIC-NARIC's recognised-institutions section and only there
    (page-Germany / page-United-Kingdom shape, 2026-09-26). That section is the
    root of trust for WHICH list is official (spec §5.1)."""
    try:
        document = lxml.html.fromstring(body)
    except (ValueError, lxml.etree.LxmlError) as error:
        raise RegisterShape(f"the ENIC-NARIC page does not parse ({error})") from error
    groups = document.xpath(
        f'//div[contains(@class, "acc-group")][.//h3[normalize-space() = "{_ENIC_HEADING}"]]'
    )
    return tuple(
        str(href)
        for group in groups
        for href in group.xpath('.//div[contains(@class, "content")]//a/@href')
    )


def _require_landed(requested: str, landed: str) -> None:
    """The bytes vouch only if they came from the site asked for: the source
    ROW is what is vouched, never whatever a redirect served (CLAUDE.md, Web
    fetching; `reader.require_same_origin`). Registrable domain, not origin:
    a register moving www -> apex or http -> https is housekeeping."""
    if registrable_domain(landed) != registrable_domain(requested):
        raise RegisterUnreachable(f"{requested}: landed on {landed or 'nothing'}")


def enic_vouches(source: ProvenanceSource, spec: ClosedList, *, fetch: Fetch | None = None) -> bool:
    fetched = (fetch or fetch_page)(source.enic_naric_page, purpose="provenance")
    if not readable_page(fetched):
        raise RegisterUnreachable(f"{source.enic_naric_page}: {fetched.outcome} {fetched.reason}")
    _require_landed(source.enic_naric_page, fetched.final_url)
    # A relative link keys to "": it must never match a source_url that has no domain.
    linked = {registrable_domain(link) for link in enic_register_links(fetched.body)} - {""}
    return registrable_domain(spec.source_url) in linked


def _require_linked(source: ProvenanceSource, spec: ClosedList, *, fetch: Fetch | None) -> None:
    """The vouched page (spec.source_url) must land on the vouched site and
    link EXACTLY the data file; else RegisterNotVouched, before the file is
    fetched. Links resolve as a browser would, against <base href> if any
    (hochschulkompass.de sets one, 2026-09-27)."""
    fetched = (fetch or fetch_page)(spec.source_url, purpose="provenance")
    if not readable_page(fetched):
        raise RegisterUnreachable(f"{spec.source_url}: {fetched.outcome} {fetched.reason}")
    try:
        _require_landed(spec.source_url, fetched.final_url)
    except RegisterUnreachable as error:
        raise RegisterNotVouched(f"{source.slug}: {error}") from error
    try:
        document = lxml.html.fromstring(fetched.body)
    except (ValueError, lxml.etree.LxmlError) as error:
        raise RegisterShape(f"{spec.source_url} does not parse ({error})") from error
    document.make_links_absolute(fetched.final_url, handle_failures="discard")
    if source.data_url not in {str(href).strip() for href in document.xpath("//a/@href")}:
        raise RegisterNotVouched(
            f"{source.slug}: {spec.source_url} does not link {source.data_url}"
        )


def _key(row: dict[str, object], source: ProvenanceSource) -> str:
    """`id_field` may join several fields with "+": Korea's names repeat across
    campuses, so its key is SCHL_NM+MAINBRANCH_NM."""
    if not source.id_field:
        return ""
    return "|".join(str(row.get(field) or "").strip() for field in source.id_field.split("+"))


def _tsv(body: bytes, source: ProvenanceSource) -> list[RegisterRow]:
    reader = csv.DictReader(io.StringIO(body.decode(source.encoding)), delimiter="\t")
    wanted = {source.name_field, source.website_field} | (set(source.id_field.split("+")) - {""})
    missing = wanted - set(reader.fieldnames or ())
    if missing:
        raise RegisterShape(f"{source.slug}: columns {sorted(missing)} are absent")
    return [
        RegisterRow(
            key=_key(dict(row), source),
            name=(row.get(source.name_field) or "").strip(),
            website=(row.get(source.website_field) or "").strip(),
        )
        for row in reader
    ]


def _json_list(body: bytes, source: ProvenanceSource) -> list[RegisterRow]:
    """The format column decides the parse, not the Content-Type: Korea serves
    its JSON as text/html. A body that is not JSON is a shape error, loud."""
    try:
        data: object = json.loads(body.decode(source.encoding))
    except ValueError as error:
        raise RegisterShape(f"{source.slug}: the body is not JSON ({error})") from error
    for part in filter(None, source.records_path.split(".")):
        data = data.get(part) if isinstance(data, dict) else None
    if not isinstance(data, list):
        raise RegisterShape(f"{source.slug}: {source.records_path or 'the body'} is not a list")
    records = [item for item in data if isinstance(item, dict)]
    for field in (source.name_field, source.website_field):
        if records and not any(field in item for item in records):
            # A renamed field would parse as rows with no website, and
            # record_list would then unbind every row the register bound.
            raise RegisterShape(f"{source.slug}: no record has the field {field!r}")
    return [
        RegisterRow(
            key=_key(item, source),
            name=str(item.get(source.name_field) or "").strip(),
            website=str(item.get(source.website_field) or "").strip(),
        )
        for item in records
    ]


def _document(body: bytes, source: ProvenanceSource) -> Any:
    # Decoded by the row's encoding: given bytes and no <meta charset>, lxml
    # reads Latin-1, and a non-ASCII anchor then never matches. Bytes, not a
    # decoded str: lxml refuses a str carrying an <?xml encoding=...?>.
    return lxml.html.fromstring(body, parser=lxml.html.HTMLParser(encoding=source.encoding))


def _html_list(body: bytes, source: ProvenanceSource) -> list[RegisterRow]:
    document = _document(body, source)
    anchors = document.xpath(
        "//*[contains(normalize-space(text()), $anchor)]", anchor=source.list_anchor
    )
    if not anchors:
        raise RegisterShape(
            f"{source.slug}: the list anchor {source.list_anchor!r} is not on the page"
        )
    own = registrable_domain(source.data_url)
    links = anchors[0].xpath("following-sibling::*[self::ul or self::ol][1]/li/a[@href]")
    return [
        RegisterRow(key="", name=link.text_content().strip(), website=str(link.get("href")).strip())
        for link in links
        if registrable_domain(str(link.get("href"))) not in ("", own)
    ]


def _html_records(body: bytes, source: ProvenanceSource) -> list[RegisterRow]:
    """One record per `records_path` match; `name_field` and `website_field`
    are XPaths relative to it (YÖK prints a card per university, its website
    in the card, 2026-09-27). XPaths live in the reviewed sources row, so a
    changed layout is a one-row diff, and a layout that no longer matches is
    the "no rows" / "no website" shape error, never an empty register."""
    try:
        records = _document(body, source).xpath(source.records_path)
    except lxml.etree.XPathError as error:
        raise RegisterShape(f"{source.slug}: records_path does not evaluate ({error})") from error
    return [
        RegisterRow(
            key=_key(dict(record.attrib), source),
            name=str(record.xpath(f"string({source.name_field})")),
            website=str(record.xpath(f"string({source.website_field})")).strip(),
        )
        for record in records
        if isinstance(record, lxml.etree._Element)
    ]


_PARSERS: dict[str, Callable[[bytes, ProvenanceSource], list[RegisterRow]]] = {
    "tsv": _tsv, "json_list": _json_list, "html_list": _html_list,
    "html_records": _html_records,
}


def parse_register(body: bytes, source: ProvenanceSource) -> tuple[RegisterRow, ...]:
    try:
        parsed = _PARSERS[source.format](body, source)
    except RegisterShape:
        raise
    except (ValueError, lxml.etree.LxmlError) as error:
        # UnicodeDecodeError is a ValueError; lxml's ParserError ("Document is
        # empty") is not. Either is the publisher's format, not our crash.
        raise RegisterShape(f"{source.slug}: the body does not parse ({error})") from error
    rows: dict[str, RegisterRow] = {}
    for row in parsed:
        # HRK quotes a name across two lines and pads others with runs of spaces.
        row = replace(row, name=" ".join(row.name.split()))
        if row.name:
            rows.setdefault((row.key or row.name)[:120], row)
    if not rows:
        raise RegisterShape(
            f"{source.slug}: no rows parsed -- the publisher changed its format, and "
            "loading nothing would read as every institution absent"
        )
    if source.website_field and not any(row.website for row in rows.values()):
        raise RegisterShape(
            f"{source.slug}: no row has a website in {source.website_field!r} -- loading "
            "it would unbind every row the register bound"
        )
    return tuple(rows.values())


_HOST = re.compile(r"[a-z0-9.-]+")
#: Where IDNA 2003 (Python's codec) and IDNA 2008 (what registries issue)
#: disagree: 2003 maps "straße.de" to strasse.de, someone else's domain.
_IDNA_DEVIATIONS = frozenset("\u00df\u03c2\u200c\u200d")


def _https(website: str) -> str:
    """Korea prints bare hosts ("kentech.ac.kr", "homepage.cnu.ac.kr/cnuip"),
    some with "//" inside the path ("www.sangji.ac.kr//grad/index.do"), so a
    scheme is what marks a URL, not a double slash.

    An internationalised host ("한국대학.kr", "türkiye.edu.tr") is written in
    its punycode form first, so it binds as the xn-- domain DNS serves.

    "" (unbound) when the host carries userinfo or, after that, anything
    outside [a-z0-9.-]: "kentech.ac.kr@evil.com" is evil.com, and "a@b.com" or
    a comma-joined pair is not one website."""
    url = website if not website or "://" in website else f"https://{website}"
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if host.isascii():
            ascii_host = host
        elif _IDNA_DEVIATIONS.isdisjoint(host):
            # ponytail: stdlib IDNA 2003; the `idna` package (IDNA 2008) if a
            # register prints a host whose deviation characters matter.
            ascii_host = host.encode("idna").decode("ascii")
        else:
            return ""
        port = f":{parts.port}" if parts.port else ""
    except (ValueError, UnicodeError):
        # UnicodeError: an empty or over-long label; ValueError: a bad port.
        return ""
    if "@" in parts.netloc or not _HOST.fullmatch(ascii_host):
        return ""
    return url if ascii_host == host else parts._replace(netloc=ascii_host + port).geturl()


def load_register(
    source: ProvenanceSource,
    *,
    now: datetime,
    fetch: Fetch | None = None,
    fetch_file: FetchFile | None = None,
    store: ObjectStore | None = None,
) -> ListReport:
    """Read one register into RegisterEntry rows through `record_list` -- the
    register's own website field is the binding (spec §5.2 rule 1). Pages
    through the vendor router, data files through our own transport (spec §6);
    the bytes read are archived before any row is written."""
    spec = ClosedList.objects.get(slug=source.slug)
    # spec.reuse_terms is not checked: recorded, not a gate (owner, 2026-09-27).
    if source.enic_naric_page and not enic_vouches(source, spec, fetch=fetch):
        raise RegisterNotVouched(
            f"{source.slug}: {source.enic_naric_page} does not link {spec.source_url}"
        )
    vouched = registrable_domain(spec.source_url)
    if registrable_domain(source.data_url) != vouched:
        # m13: ENIC-NARIC vouches spec.source_url's site, so a file elsewhere
        # counts only if that site links it (HRK: hochschulkompass.de's
        # downloads page links hs-kompass.de). A hand reason exempts only a
        # register with no ENIC-NARIC page (Korea, SFC, Türkiye).
        if source.enic_naric_page:
            _require_linked(source, spec, fetch=fetch)
        elif not source.named_by_hand_because:
            raise RegisterNotVouched(f"{source.slug}: {source.data_url} is not on {vouched}")
    if source.format.startswith("html_"):
        fetched = (fetch or fetch_page)(source.data_url, purpose="provenance")
        if not readable_page(fetched):
            raise RegisterUnreachable(f"{source.slug}: {fetched.outcome} {fetched.reason}")
        landed, body = fetched.final_url, fetched.body
    else:
        try:
            result = (fetch_file or fetch_data_file)(
                source.data_url, max_bytes=source.max_bytes, require_https=True
            )
        except (SourceBlocked, UnsafeTarget) as error:
            # UnsafeTarget also covers a DNS failure (validate_public_url).
            raise RegisterUnreachable(f"{source.slug}: {error!r}") from error
        landed, body = result.final_url, result.body
    _require_landed(source.data_url, landed)
    parsed = parse_register(body, source)
    if spec.printed_size and len(parsed) != spec.printed_size:
        raise RegisterShape(
            f"{source.slug}: parsed {len(parsed)} rows, the publisher prints {spec.printed_size}"
        )
    (store or S3ObjectStore()).put(f"registers/{source.slug}/{now:%Y-%m-%dT%H%M%S}", body)
    host_cells = (spec.country_code,) if spec.country_code else ("ANY",)
    rows = tuple(
        ListRow(
            external_key=(row.key or row.name)[:120], name=row.name[:300], kind="INSTITUTION",
            website=_https(row.website), page_url="", country_code=spec.country_code,
            home_cells=("ANY",), host_cells=host_cells, rejected_reason="",
            source_url=source.data_url, verified_on=now.date(),
        )
        for row in parsed
    )
    report = record_list(spec, rows, now=now)
    ClosedList.objects.filter(slug=spec.slug).update(loaded_at=now)
    return report


def register_country(country: str, domain: str) -> str:
    """Which country's registers to LOAD for a body (ruling I3): its own
    country, else its domain's ccTLD ("kentech.ac.kr" -> KR). A load choice,
    never evidence: admission still needs the register's own website field to
    name the domain. A generic TLD gives "" and no register is loaded."""
    if country:
        return country
    suffix = domain.rsplit(".", 1)[-1].upper()
    if len(suffix) != 2 or not suffix.isalpha():
        return ""
    return {"UK": "GB"}.get(suffix, suffix)


def country_registers(country: str, sources: Iterable[ProvenanceSource]) -> list[ProvenanceSource]:
    if not country:
        return []
    in_country = set(ClosedList.objects.filter(country_code=country).values_list("slug", flat=True))
    return [
        source for source in sources
        if source.role == Reason.REGISTER and source.slug in in_country
    ]


def ensure_country_loaded(
    country: str,
    *,
    now: datetime,
    cycle: timedelta,
    sources: Iterable[ProvenanceSource],
    load: Callable[..., object] | None = None,
    **load_kwargs: Any,
) -> str:
    """Load a country's registers when stale, one loader at a time (spec §7.1:
    two students reaching Germany at once cause one load). Returns "ok",
    "none" (no register for the country), "busy" (another loader holds the
    lease) or "failed" (logged; the country stays not loaded)."""
    registers = country_registers(country, sources)
    if not registers:
        return "none"
    # Every register is tried: one failing (OfS) must not starve another (SFC).
    # The answer is the worst outcome, because the country is loaded only
    # when every one of its registers is.
    outcomes = {"ok"}
    for source in registers:
        loaded_at = ClosedList.objects.values_list("loaded_at", flat=True).get(slug=source.slug)
        if loaded_at is not None and loaded_at > now - cycle:
            continue
        try:
            with transaction.atomic():
                acquire_domain_lease(f"register:{source.slug}", interval=LOAD_LEASE)
        except DomainBusy:
            outcomes.add("busy")
            continue
        try:
            (load or load_register)(source, now=now, **load_kwargs)
        except (RegisterShape, RegisterNotVouched, RegisterUnreachable, ListFileError) as error:
            logger.warning("register %s not loaded: %s", source.slug, error)
            outcomes.add("failed")
    return next(worst for worst in ("failed", "busy", "ok") if worst in outcomes)


def register_state(country: str, sources: Iterable[ProvenanceSource]) -> str:
    """For a body no register names. "absent" only when every loaded row is
    bound by the register itself: an unbound row, or one the resolver bound by
    name (ruling I6), could be this body, so absence is not established and
    the answer is "unbound_rows" -> no_domain_binding."""
    slugs = [source.slug for source in country_registers(country, sources)]
    if not slugs or ClosedList.objects.filter(slug__in=slugs, loaded_at__isnull=True).exists():
        return "not_loaded"
    if RegisterEntry.objects.filter(register__in=slugs).exclude(
        resolution=RegisterEntry.Resolution.RESOLVED, resolved_via=ResolvedVia.LISTED
    ).exists():
        return "unbound_rows"
    return "absent"


def ror_recognitions(
    facts: RorFacts, domain: str, sources: Iterable[ProvenanceSource]
) -> tuple[Recognition, ...]:
    """A register row with no website, bound to `domain` because the row's
    identifier is one ROR carries for this exact domain. Never a name."""
    found: list[Recognition] = []
    registers = [
        source for source in sources if source.role == Reason.REGISTER and source.id_scheme
    ]
    for scheme, value in sorted(facts.identifiers):
        slugs = [source.slug for source in registers if source.id_scheme == scheme]
        entry = (
            RegisterEntry.objects.filter(register__in=slugs, external_key=value)
            # A CONFLICT row is bound to neither body -- a person decides
            # (models.py's Resolution.CONFLICT); UNRESOLVED still admits.
            .exclude(resolution=RegisterEntry.Resolution.CONFLICT)
            .first()
        )
        if entry is None:
            continue
        spec = ClosedList.objects.get(slug=entry.register)
        if not (spec.loaded_at and entry.last_seen >= spec.loaded_at):
            # Same delisting rule as list_recognitions (~179-185): a row
            # older than the register's last load is one that load did not
            # see, i.e. an institution the register has since delisted.
            continue
        found.append(
            Recognition(
                reason=Reason.REGISTER, bound_domain=domain, source_slug=entry.register,
                source_url=spec.source_url, list_date=spec.verified_on.isoformat(),
                country_code=spec.country_code, identifier=(scheme, value), admitted_via="ror",
            )
        )
    return tuple(found)
