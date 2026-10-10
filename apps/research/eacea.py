"""Every Erasmus Mundus Joint Master, from the funder's own records (spec 6.2).

`POST ec.europa.eu/programmes/service/search/project/search`, filtered on
`projectLevel3` with both action codes (docs/research/eacea-actions.csv). The
complete EMJM list: every EMJM is an EU-funded project. Europa reuse notice,
so persisting what it returns is permitted -- and that does not generalise to
a search provider (CLAUDE.md).

What it answers alone: the projects, their funded period, and each project's
coordinator and partners (name, country, city, EU-PIC, website). What it does
not: which `Program` row a project is (a person, 09-14 section 8), and whether
a partner awards degrees (it records CNR and NGOs too) -- so every partner is
a CANDIDATE of kind UNSTATED for the classifier.

The partner binding is the 09-14 design's, against OUR register rather than
DEQAR's (CLAUDE.md, "two designs this supersedes in part"): EU-PIC first, the
website second, and two keys naming two bodies is a question for a person.
DEQAR's succession walk is not here, so a partner that merged binds to
whichever body holds its old PIC or domain -- the limit the gate report names.

Shape: the organisation keys below are the ones 09-14 section 3 records
verbatim. The project keys (`_PROJECT_ID`, `_PROJECT_TITLE`, `_PROJECT_START`,
`_PROJECT_END`) are UNVERIFIED placeholders pending a live capture: egress to
ec.europa.eu was blocked when this was written (2026-09-26), and the fixture
in tests/research/fixtures/eacea_emjm_page.json is hand-built around these
same names, so it cannot confirm them. The failure is loud, not wrong rows:
`record_projects` skips a project with no identifier, so a wrong
`_PROJECT_ID` yields zero projects, and entries fall short of the API's own
total (`set_printed_size`), which fails the coverage gate.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from django.db import transaction

from .closed_lists import DATA_DIR
from .egress import fetch_json_api
from .hosts import registrable_domain
from .models import (
    ClosedList,
    Organisation,
    OrganisationDomain,
    OrganisationIdentifier,
    RegisterEntry,
    RegisterEntryPartner,
    ResolvedVia,
    person_decided,
)
from .register import record_organisation

ENDPOINT = "https://ec.europa.eu/programmes/service/search/project/search"
ACTIONS = DATA_DIR / "eacea-actions.csv"
REGISTER = "eacea_emjm"
_HEADERS = {
    "Origin": "https://erasmus-plus.ec.europa.eu",
    "Referer": "https://erasmus-plus.ec.europa.eu/",
}
_ORG_MARK = "organisationPIC"
#: From a live capture (2026-10-05, tests/research/fixtures/eacea_emjm_page.json).
#: `projectName` is the grant number (e.g. 101127959); `projectId` is a UUID.
_PROJECT_ID = "projectName"
_PROJECT_TITLE = "projectTitle"
_PROJECT_START = "projectStartDate"
_PROJECT_END = "projectEndDate"
Disposition = RegisterEntryPartner.Disposition


class TotalShape(ValueError):
    """A total outside the action's bounds -- the silent-filter trap."""


@dataclass(frozen=True)
class ActionRow:
    code: str
    label: str
    index: str
    min_total: int
    max_total: int


@dataclass(frozen=True)
class ProjectFields:
    identifier: str
    title: str
    start: date | None
    end: date | None


@dataclass(frozen=True)
class EaceaReport:
    projects: int = 0
    partners: int = 0
    by_disposition: tuple[tuple[str, int], ...] = ()


def read_actions(path: Path = ACTIONS) -> tuple[ActionRow, ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(
            ActionRow(row["code"], row["label"], row["index"], int(row["min_total"]),
                      int(row["max_total"]))
            for row in csv.DictReader(handle)
        )


def payload(row: ActionRow, *, start: int, size: int) -> dict[str, object]:
    return {
        "from": start, "index": row.index, "keyword": "", "matchAllCountries": False,
        "project": {"projectLevel3": row.code}, "coordinator": {}, "partner": {},
        "organisation": {"organisationRole": "COORDINATOR_OR_PARTNER"},
        "size": size, "sort": "", "withAggregations": False,
    }


def organisations_in(node: object) -> Iterator[dict[str, object]]:
    """Every organisation dict under `node`, found by its documented key, so
    the walk does not depend on where the response nests them."""
    if isinstance(node, dict):
        if _ORG_MARK in node:
            yield node
            return
        for value in node.values():
            yield from organisations_in(value)
    elif isinstance(node, list):
        for value in node:
            yield from organisations_in(value)


def projects_in(body: dict[str, object]) -> list[dict[str, object]]:
    """The response's project list: the top-level list whose items hold
    organisations."""
    for value in body.values():
        if isinstance(value, list) and value and any(organisations_in(value[0])):
            return [item for item in value if isinstance(item, dict)]
    return []


def _day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def project_fields(project: dict[str, object]) -> ProjectFields:
    return ProjectFields(
        identifier=str(project.get(_PROJECT_ID, "")),
        title=str(project.get(_PROJECT_TITLE, ""))[:300],
        start=_day(project.get(_PROJECT_START)),
        end=_day(project.get(_PROJECT_END)),
    )


def fetch_projects(
    row: ActionRow, *, call: Callable[..., dict[str, object]] = fetch_json_api, size: int = 100
) -> tuple[int, list[dict[str, object]]]:
    """Every project under one action code, with the total asserted first and
    the paged count asserted last.

    Paging advances by what a page returned, never by what was asked for, and
    counts distinct identifiers: a server that caps the page size would
    otherwise skip projects, and one that ignores `from` (the `level3` trap
    again) would return page 0 until the count looked complete.
    """
    projects: dict[str, dict[str, object]] = {}
    start, total = 0, None
    while total is None or start < total:
        body = call(ENDPOINT, payload=payload(row, start=start, size=size), headers=_HEADERS)
        if total is None:
            try:
                total = int(str(body.get("total", -1)))
            except ValueError as error:
                raise TotalShape(
                    f"{row.code}: total {body.get('total')!r} is not a number"
                ) from error
            if not row.min_total <= total <= row.max_total:
                raise TotalShape(
                    f"{row.code}: total {total} outside {row.min_total}-{row.max_total}"
                )
        page = projects_in(body)
        before = len(projects)
        for project in page:
            projects.setdefault(project_fields(project).identifier, project)
        if len(projects) == before:
            break  # an empty page, or one that repeats what we already hold
        start += len(page)
    projects.pop("", None)
    if len(projects) != total:
        raise TotalShape(
            f"{row.code}: paged {len(projects)} distinct projects against total {total}"
        )
    return total or 0, list(projects.values())


def _held_by_pic(pic: str) -> Organisation | None:
    row = OrganisationIdentifier.objects.select_related("organisation").filter(
        scheme="EACEA_PIC", value=pic
    ).first()
    return row.organisation if row else None


def _held_by_domain(domain: str) -> Organisation | None:
    row = OrganisationDomain.objects.select_related("organisation").filter(
        registrable_domain=domain
    ).first()
    return row.organisation if row else None


def bind_partner(org_row: dict[str, object]) -> tuple[Organisation | None, str]:
    """One participating organisation -> (body, disposition). PIC first."""
    pic = str(org_row.get("organisationPIC", "")).strip()
    website = str(org_row.get("organisationWebsite", "") or "").strip()
    domain = registrable_domain(website) if website else ""
    by_pic = _held_by_pic(pic) if pic else None
    by_domain = _held_by_domain(domain) if domain else None
    if by_pic and by_domain and by_pic.pk != by_domain.pk:
        return None, Disposition.CONFLICT
    if pic and by_domain and not by_pic and by_domain.identifiers.filter(
        scheme="EACEA_PIC"
    ).exclude(value=pic).exists():
        # The website's body already carries a different PIC: a hospital or
        # a consortium site naming its university's domain. Attaching this
        # PIC would make it resolve to that body from now on, decided by
        # processing order. A person decides instead.
        return None, Disposition.CONFLICT
    if not domain:
        return (by_pic, Disposition.BOUND_PIC) if by_pic else (None, Disposition.NO_KEY)
    name = str(org_row.get("organisationName", "")).strip()[:300] or domain
    org = record_organisation(
        domain=domain, name=name, names=(name,), kind="UNSTATED",
        country_code=str(org_row.get("organisationCountry", "")).strip().upper()[:2],
        found_via="EACEA:emjm", identifiers=[("EACEA_PIC", pic)] if pic else (),
        status=Organisation.Status.CANDIDATE,
    )
    if by_pic and by_domain:
        return org, Disposition.BOUND_BOTH
    if by_pic:
        return org, Disposition.BOUND_PIC
    if by_domain:
        return org, Disposition.BOUND_DOMAIN
    return org, Disposition.NEW


def record_projects(projects: list[dict[str, object]], *, now: datetime) -> EaceaReport:
    tally: dict[str, int] = {}
    project_count = partner_count = 0
    for project in projects:
        fields = project_fields(project)
        if not fields.identifier:
            continue
        project_count += 1
        with transaction.atomic():
            listed_facts: dict[str, object] = {
                "name": fields.title or fields.identifier, "listed_from": fields.start,
                "listed_until": fields.end, "home_cells": ["ANY"], "host_cells": ["ANY"],
                "last_seen": now,
            }
            stored = RegisterEntry.objects.filter(
                register=REGISTER, external_key=fields.identifier[:120]
            ).values_list("resolution", "resolved_via").first()
            # A person answered this row in the resolution queue (usually the
            # coordinator CONFLICT below): its binding is kept, and only the
            # list's own facts and partner rows are refreshed.
            kept = stored is not None and person_decided(*stored)
            entry, _ = RegisterEntry.objects.update_or_create(
                register=REGISTER, external_key=fields.identifier[:120],
                defaults=listed_facts if kept else {
                    **listed_facts,
                    "resolution": RegisterEntry.Resolution.UNRESOLVED, "resolved_via": "",
                    # Rebound below from this run's coordinator, never kept
                    # from a previous run's.
                    "organisation": None,
                },
            )
            # The live response lists every organisation twice: under
            # `organisations` and again under `coordinator` or `partners`.
            seen: set[str] = set()
            for org_row in organisations_in(project):
                pic = str(org_row.get("organisationPIC", "")).strip()
                if not pic or pic in seen:
                    continue
                seen.add(pic)
                org, disposition = bind_partner(org_row)
                role = str(org_row.get("organisationRole", "")).upper()[:12]
                RegisterEntryPartner.objects.update_or_create(
                    entry=entry, listed_identifier=pic,
                    defaults={
                        "organisation": org, "role": role,
                        "listed_name": str(org_row.get("organisationName", ""))[:300],
                        "listed_domain": registrable_domain(
                            str(org_row.get("organisationWebsite", "") or "")
                        ),
                        "country_code": str(org_row.get("organisationCountry", ""))[:2],
                        "disposition": disposition,
                    },
                )
                partner_count += 1
                tally[disposition] = tally.get(disposition, 0) + 1
                if role == "COORDINATOR" and not kept:
                    entry.organisation = org
                    entry.resolution = (
                        RegisterEntry.Resolution.CONFLICT if disposition == Disposition.CONFLICT
                        else RegisterEntry.Resolution.RESOLVED if org
                        else RegisterEntry.Resolution.UNRESOLVED
                    )
                    # The coordinator's PIC/website is the list's own key.
                    entry.resolved_via = (
                        ResolvedVia.LISTED
                        if entry.resolution == RegisterEntry.Resolution.RESOLVED else ""
                    )
            if not kept:
                entry.unresolved_reason = ""
                entry.save(update_fields=[
                    "organisation", "resolution", "resolved_via", "unresolved_reason",
                ])
    return EaceaReport(project_count, partner_count, tuple(sorted(tally.items())))


def set_printed_size(total: int) -> None:
    """The API's own total is the list's printed size -- 100% enumerated means
    entries == the sum across both action codes."""
    ClosedList.objects.filter(slug=REGISTER).update(printed_size=total)
