"""Türkiye's foundations register, filtered to the ones that say they award
scholarships -- rung 1 of the ladder (spec 6.2), and the only register in the
launch corridor that carries the purpose.

4,076 of 6,857 foundations on 2026-09-24. The page is client-side (a plain GET
returns "YÜKLENİYOR"), so it is read through the vendor fetch seam like any
page; the register's bytes are parsed and discarded, and nothing a vendor
returns is stored. Each row carries name, address, district/city, phone,
e-tebligat id and e-mail -- no website. Rung 0 (`domains.email_domain`) turns
two-thirds of the e-mails into hosts for free; the rest wait for the resolver.

Reuse terms: unread (spec 19). A `.gov.tr` register, read for names only.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

import lxml.html
from django.db import transaction

from .classify import _USABLE
from .domains import email_domain
from .fetch import SweepBudget, fetch_page
from .fetch.types import FetchedPage
from .models import Organisation, RegisterEntry, ResolvedVia, refreshed_resolution
from .register import record_organisation

logger = logging.getLogger(__name__)

VGM_URL = "https://www.vgm.gov.tr/vakif-sorgulama/vakif-sorgulama"
REGISTER = "vgm_tr"
#: The page prints "4076" beside the results heading. A register that suddenly
#: reads in the hundreds or the hundreds of thousands is a changed page or a
#: dropped filter, and either is a stop, never a silent overwrite.
_TOTAL_FLOOR, _TOTAL_CEILING = 1_000, 20_000
_TOTAL = re.compile(
    r"(?<!\d)(\d{1,2}[.,]?\d{3})(?!\d)\s*(?:Adet\s*Sonu[cç]|kay[ıi]t)", re.IGNORECASE
)


class RegisterShape(ValueError):
    """The page did not look like the register we measured."""


@dataclass(frozen=True)
class VgmRow:
    name: str
    city: str
    notification_id: str
    email: str


def vgm_page_url(page: int, page_size: int) -> str:
    return f"{VGM_URL}?{urlencode({'Page': page, 'IsGrant': 'true', 'PageSize': page_size})}"


def _tree(html: bytes) -> lxml.html.HtmlElement:
    # The captured page carries no charset declaration at all (no <meta
    # charset>, no Content-Type in the markup), and the response is real
    # UTF-8 -- measured on the 2026-09-24 capture, where the İ/Ş/Ğ names
    # decode correctly as UTF-8 and lxml's own encoding sniffing on the raw
    # bytes guesses a Latin encoding instead, turning "YETİMLER" into
    # "YETÄ°MLER" silently. Decoding to str first and handing lxml a unicode
    # string bypasses that sniff entirely -- do not pass `html` to lxml
    # unparsed again.
    return lxml.html.fromstring(html.decode("utf-8"))


def _cells(tr: lxml.html.HtmlElement) -> list[str]:
    return [" ".join(td.text_content().split()) for td in tr.findall("td")]


def parse_vgm_page(html: bytes) -> tuple[VgmRow, ...]:
    """Every foundation row on one rendered page, in page order.

    Column order as the page renders it -- VAKIF ADI, ADRES, İLÇE / ŞEHİR,
    TELEFON / FAKS, E-TEBLİGAT ADRESİ, E-POSTA -- and a row is a <tr> with at
    least six cells and a name. Header rows and layout tables have neither.
    """
    tree = _tree(html)
    rows: list[VgmRow] = []
    for tr in tree.iter("tr"):
        cells = _cells(tr)
        if len(cells) < 6 or not cells[0]:
            continue
        name, _address, city, _phone, notification_id, email = cells[:6]
        rows.append(
            VgmRow(name=name, city=city, notification_id=notification_id, email=email.casefold())
        )
    return tuple(rows)


def vgm_total(html: bytes) -> int | None:
    """The count the page prints, or None when the marker is absent."""
    text = " ".join(_tree(html).text_content().split())
    match = _TOTAL.search(text)
    if not match:
        return None
    return int(match.group(1).replace(".", "").replace(",", ""))


def read_vgm(
    *,
    fetch: Callable[..., FetchedPage] = fetch_page,
    page_size: int = 50,
    max_pages: int | None = None,
    budget: SweepBudget | None = None,
    start_page: int = 1,
) -> Iterator[tuple[VgmRow, ...]]:
    """Every page of the register from `start_page`, until a page past the
    printed total comes back empty.

    The first page FETCHED IN THIS RUN's printed total is asserted against
    the thousands: below the floor the filter dropped or the page is a
    shell, above the ceiling the filter is gone -- both are RegisterShape,
    never a partial run that looks complete. That same page also fixes
    `per_page` (however many rows it actually carried -- the endpoint
    ignores `PageSize`) and, with the total, `last_page`. Page 52 of 4,076
    came back FETCHED/200 with an empty table on 2026-09-24 -- a rendered
    shell, the XHR hadn't filled it yet -- so an empty page at or before
    `last_page` is not the end: ponytail, one same-URL retry, then named in
    a RegisterShape if it's still empty. Only an empty page past `last_page`
    ends the run; a page past it that still has rows is fine, the total is
    a floor, not a contract. `max_pages` is the operator's probe knob (it
    counts pages fetched in THIS run, not the page number -- a resumed run
    of `max_pages=2` starting at page 225 fetches 225 and 226, never zero),
    not a budget; `budget` is the fetch budget and stops the run the way
    any sweep stops.

    `start_page` resumes a run a transient vendor refusal interrupted
    partway through: `record_vgm` is idempotent, so re-fetching from
    `start_page` re-records nothing already recorded and does not re-spend
    credits on pages already read. `start_page < 1` is a ValueError, raised
    before any fetch.
    """
    if start_page < 1:
        raise ValueError(f"start_page must be >= 1, got {start_page}")

    def _rows(p: int) -> tuple[FetchedPage, tuple[VgmRow, ...]]:
        fetched = fetch(vgm_page_url(p, page_size), purpose="read", tag="vgm", budget=budget)
        if fetched.outcome not in _USABLE:
            raise RegisterShape(f"VGM page {p} refused: {fetched.outcome} {fetched.reason}")
        return fetched, parse_vgm_page(fetched.body)

    page, per_page, last_page = start_page, 1, 1
    total: int | None = 0
    fetched_pages = 0
    while max_pages is None or fetched_pages < max_pages:
        fetched, rows = _rows(page)
        if page == start_page:
            total = vgm_total(fetched.body)
            if total is None or not _TOTAL_FLOOR <= total <= _TOTAL_CEILING:
                raise RegisterShape(f"VGM printed total {total!r} at {fetched.final_url}")
            if not rows:
                raise RegisterShape(
                    f"VGM page {page} rendered empty at {fetched.final_url} (total {total})"
                )
            per_page = len(rows)
            last_page = -(-total // per_page)  # ceil
        if not rows:
            if page > last_page:
                return
            fetched, rows = _rows(page)
            if not rows:
                raise RegisterShape(
                    f"VGM page {page} rendered empty twice at {fetched.final_url} "
                    f"(total {total}, {per_page} per page)"
                )
        yield rows
        fetched_pages += 1
        page += 1


@dataclass(frozen=True)
class LadderReport:
    listed: int = 0
    resolved: int = 0
    unresolved: int = 0
    organisations_new: int = 0
    organisations_known: int = 0
    #: Rows carrying no e-tebligat id, keyed on `f"name:{row.name}"` instead --
    #: a name is never a lookup key anywhere else in this codebase, so the
    #: prefix says so and this count says how often it happened.
    name_keyed: int = 0


def record_vgm(rows: Iterable[VgmRow], *, now: datetime) -> LadderReport:
    """Write the register's rows, and rung 0 of resolution, nothing more.

    A row with an own-domain e-mail becomes a REGISTERED PRIVATE_FOUNDATION in
    Türkiye -- the register vouches for all three facts -- keyed on that domain
    through `record_organisation`, which decides whether it is a body we hold
    already. A free-mail row is UNRESOLVED: counted in the denominator, bound
    to nothing, the resolver's queue (spec 6.5). No name is ever a key for an
    ORGANISATION -- but a `RegisterEntry` with no notification_id has nothing
    else to key on, so it falls back to `name:<name>`, counted in `name_keyed`
    below. A key whose stored name changes between runs is logged, not merged.
    A row a person answered in the resolution queue (bound HUMAN, or REFUSED)
    keeps that answer on every re-read (`person_decided`) and counts as
    `unresolved` -- rung 0 did not bind it.
    """
    listed = resolved = unresolved = new = known = name_keyed = 0
    for row in rows:
        listed += 1
        domain = email_domain(row.email)
        keyed_on_name = not row.notification_id
        external_key = row.notification_id or f"name:{row.name}"
        if keyed_on_name:
            name_keyed += 1
        with transaction.atomic():
            stored = RegisterEntry.objects.filter(
                register=REGISTER, external_key=external_key
            ).values_list("name", "resolution", "resolved_via").first()
            renamed = stored is not None and stored[0] != row.name
            if stored is not None and renamed:
                logger.warning(
                    "register %s key %s: stored name %r does not match %r",
                    REGISTER, external_key, stored[0], row.name,
                )
            # Precedence: a person's answer (item 12) > the register's own
            # e-mail > the resolver's earlier binding > withdrawn.
            fields, kept = refreshed_resolution(stored, row.name, domain, ResolvedVia.EMAIL)
            refreshed: dict[str, object] = {
                "name": row.name, "city": row.city, "contact_domain": domain, "last_seen": now,
            }
            refreshed |= fields
            if renamed and not kept:
                # The resolver answered for the OLD name, and Wikidata's variants
                # were variants of it: a renamed row starts over as never tried.
                refreshed |= {
                    "names": [row.name], "unresolved_reason": "",
                    "resolution_attempted_at": None,
                }
            entry, _ = RegisterEntry.objects.update_or_create(
                register=REGISTER,
                external_key=external_key,
                defaults=refreshed,
                create_defaults={**refreshed, "names": [row.name]},
            )
            if kept or not domain:
                unresolved += 1
                continue
            existed = Organisation.objects.filter(primary_domain=domain).exists()
            org = record_organisation(
                domain=domain, name=row.name, names=(row.name,), kind="PRIVATE_FOUNDATION",
                country_code="TR", found_via="R1_REGISTER:vgm",
                status=Organisation.Status.REGISTERED,
            )
            if entry.organisation_id != org.id:
                entry.organisation = org
                entry.save(update_fields=["organisation"])
        resolved += 1
        if existed:
            known += 1
        else:
            new += 1
    return LadderReport(listed, resolved, unresolved, new, known, name_keyed)


@dataclass(frozen=True)
class Coverage:
    listed: int
    bodies_known: int
    resolved: int
    unresolved: int
    classified: int
    funds_students: int


def register_coverage(register: str) -> Coverage:
    """The coverage line, as arithmetic (spec 10.6): what the list names, what we hold.

    `listed`, `resolved` and `unresolved` are entry counts -- one row of the
    list. `bodies_known`, `classified` and `funds_students` are DISTINCT
    organisation counts -- two entries (a branch office, a second e-mail) can
    bind to the same body, and counting entries there double-counts it.
    """
    entries = RegisterEntry.objects.filter(register=register)
    bound = entries.filter(organisation__isnull=False)
    return Coverage(
        listed=entries.count(),
        bodies_known=bound.values("organisation").distinct().count(),
        resolved=entries.filter(resolution=RegisterEntry.Resolution.RESOLVED).count(),
        unresolved=entries.filter(resolution=RegisterEntry.Resolution.UNRESOLVED).count(),
        classified=bound.filter(organisation__classified_at__isnull=False)
        .values("organisation").distinct().count(),
        funds_students=bound.filter(organisation__funds_students=True)
        .values("organisation").distinct().count(),
    )
