"""The only code that inserts a ResolutionItem, and the only code that withdraws one.

Called from catalogue-side runs (discover, classify_organisations, the funding
reader, the resolver's CONFLICT branches), which run as `runtime_engine` or
the table owner. `runtime_web` has no INSERT or DELETE policy on this table
(research/0013), so a console view that called this would be refused by the
database, not merely by convention.

`subject_facts` reads the catalogue, which `runtime_web` holds no grant on
(funding/0049). That is why the two facts the console sorts by are stamped
here, at filing, and never looked up from a view (brief D3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import get_args
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from apps.funding.models import FundingOpportunity, OfficialSourceSnapshot
from apps.research import funding_judge
from apps.research.discovery import canonicalize_url
from apps.research.hosts import registrable_domain
from apps.research.models import (
    FetchAttempt,
    HostProfile,
    MovedPage,
    Organisation,
    OrganisationDomain,
    ResolutionItem,
)

from .kinds import KINDS


def _organisation_for(subject_key: str) -> Organisation | None:
    """The organisation a subject belongs to, if the register holds one."""
    prefix, _, key = subject_key.partition(":")
    if prefix == "organisation":
        found = Organisation.objects.filter(primary_domain=key).first()
        if found is not None:
            return found
    if prefix in {"host", "organisation"}:
        domain = registrable_domain(key)
        if not domain:
            # "" keys nothing; matching on it would be a guess (hosts.py).
            return None
        match = (
            OrganisationDomain.objects.select_related("organisation")
            .filter(registrable_domain=domain)
            .first()
        )
        return match.organisation if match else None
    if prefix == "award":
        row = (
            FundingOpportunity.objects.filter(canonical_key=key)
            .select_related("organisation")
            .first()
        )
        return row.organisation if row else None
    return None  # register: -- by definition no organisation yet


def subject_facts(subject_key: str, evidence: Mapping[str, object]) -> tuple[str, bool]:
    """`(country_code, registered)` for a subject, from the catalogue.

    Engine-side only: the kind wrappers call it and pass the answer to
    `file_item`. A subject with no organisation falls back to the evidence's
    own `country_code` (a SITE_UNKNOWN register row carries one) and is never
    `registered` -- the sort's "registered hosts first" is about a body a
    register vouched for, and there is no body yet.
    """
    org = _organisation_for(subject_key)
    if org is not None:
        return org.country_code, org.status == Organisation.Status.REGISTERED
    country = evidence.get("country_code", "")
    return (country if isinstance(country, str) else ""), False


def _valid_country(code: str) -> None:
    if code and not (len(code) == 2 and code.isascii() and code.isupper()):
        raise ValueError(f"country_code is ISO 3166 alpha-2 or empty, not {code!r}")


@transaction.atomic
def file_item(
    kind: str,
    subject_key: str,
    evidence: Mapping[str, object],
    *,
    country_code: str = "",
    registered: bool = False,
    now: datetime | None = None,
) -> ResolutionItem:
    """File one live question, or refresh the one already filed for this subject.

    Refreshes evidence, ask and the subject facts **only while OPEN**: a parked
    item keeps what the parking operator saw, and a decided one what the
    decision was made against. `expires_at` is counted from first filing.
    """
    spec = KINDS[kind]
    if not subject_key.startswith(spec.subject_prefix):
        raise ValueError(f"{kind} subjects start with {spec.subject_prefix!r}")
    _valid_country(country_code)
    try:
        parsed = spec.evidence.model_validate(evidence)
    except ValidationError as error:
        raise ValueError(f"{kind} evidence refused: {error.error_count()} error(s)") from error
    at = now or timezone.now()
    fresh = {
        "evidence": parsed.model_dump(mode="json"),
        "ask": spec.render_ask(parsed),
        "country_code": country_code,
        "registered": registered,
        "refreshed_at": at,
    }
    item, created = ResolutionItem.objects.select_for_update().get_or_create(
        kind=kind,
        subject_key=subject_key,
        defaults={
            **fresh,
            "options": list(spec.options),
            "expires_at": at + timedelta(days=settings.RESOLUTION_EXPIRY_DAYS),
        },
    )
    if not created and item.state == ResolutionItem.State.OPEN:
        for name, value in fresh.items():
            setattr(item, name, value)
        item.save(update_fields=list(fresh))
    return item


def withdraw_item(kind: str, subject_key: str) -> bool:
    """The machine answered it. Never touches a DECIDED item -- a person's
    answer is applied or refused by the applier, not silently dropped."""
    deleted, _ = ResolutionItem.objects.filter(
        kind=kind,
        subject_key=subject_key,
        state__in=(ResolutionItem.State.OPEN, ResolutionItem.State.PARKED),
    ).delete()
    return bool(deleted)


# --- AWARD_DISPUTED (plan Task 8) -------------------------------------------

#: The disputed fields an operator may answer, each with the judge's own
#: closed vocabulary. The Literal aliases are read, never hand-copied, so a
#: label the judge gains or loses reaches the choices by itself
#: (test_award_writer pins it). An existence split (`offered`, `holder`,
#: `scope`) is not here: "not an award" and "third party's money" are exactly
#: its answers. Nor are the card's own fields (`timing`, `cycle`, `amount`,
#: `duration`): the applier sets only these five columns.
AWARD_VOCABULARIES: dict[str, object] = {
    "money_form": funding_judge._Money,
    "route": funding_judge._Route,
    "nationality_shape": funding_judge._Nationality,
    "internationals_included": funding_judge._Stated,
    "kind": funding_judge._Kind,
}

#: What the reader's rows need from a person. ABSTAINED is not here (a reading
#: failed: the reader's retry to make), nor WITHDRAWN (the page stopped saying it).
_ASKABLE = ("UNAGREED", "AGREED")


def award_choices(field: str) -> list[str]:
    """`field`'s vocabulary minus UNSTATED, which is not an answer."""
    return [value for value in get_args(AWARD_VOCABULARIES[field]) if value != "UNSTATED"]


def award_subject(row: FundingOpportunity) -> str:
    return f"award:{row.canonical_key}"


def award_why(row: FundingOpportunity) -> str:
    """One sentence: why this row is waiting for a person."""
    if row.suspension_quote:
        # First, and before anything about agreement: an operator who is not
        # shown this sentence cannot be blamed for accepting the row.
        return f"ITS OWN PAGE WITHDREW IT: {row.suspension_quote}"
    if row.agreement == "AGREED":
        return "agreed, but names no benefit or form of money, or its lead cannot be served"
    if row.agreement == "ABSTAINED":
        return "a reading failed, so the three could not be compared"
    return "the readings disagreed"


def award_needs_a_person(row: FundingOpportunity) -> bool:
    """The plan's "files" rows: a reader row nobody -- machine or person --
    has answered, whose page has not answered it either."""
    return (
        row.kind.startswith("I")
        and row.agreement in _ASKABLE
        and not row.served
        and not row.review
        and not row.suspension_quote
    )


def award_evidence(
    row: FundingOpportunity, snapshot: OfficialSourceSnapshot
) -> dict[str, object] | None:
    """The item's evidence for one page version, or None when that version
    carries no quote to show (then there is nothing a person could judge)."""
    quotes = sorted(
        set(row.evidence_claims.filter(snapshot=snapshot).values_list("claim", flat=True))
    )
    if not quotes:
        return None
    split = set(filter(None, row.disputed.split(";")))
    return {
        "canonical_key": row.canonical_key,
        "award_name": row.name[:80],
        "page_url": snapshot.source.canonical_url,
        "snapshot_sha256": snapshot.sha256,
        "quotes": quotes[:12],
        "disputed": [
            {"field": name, "choices": award_choices(name)}
            for name in AWARD_VOCABULARIES
            if name in split
        ],
        "why": award_why(row)[:300],
    }


def file_award_dispute(
    row: FundingOpportunity, snapshot: OfficialSourceSnapshot
) -> ResolutionItem | None:
    """File (or refresh) the AWARD_DISPUTED item for one row on one page version."""
    evidence = award_evidence(row, snapshot)
    if evidence is None:
        return None
    subject = award_subject(row)
    country_code, registered = subject_facts(subject, evidence)
    return file_item(
        "AWARD_DISPUTED", subject, evidence, country_code=country_code, registered=registered
    )


def _trail(url: str) -> list[dict[str, object]]:
    """The last ten `FetchAttempt` rows for `url`, oldest first, as TrailSteps.

    Mapped field for field; the one fact TrailStep has no field for, the HTTP
    status, leads the reason rather than being dropped. A rung outside
    TrailStep's 0-9 cannot be written by the ladder (rungs are 0-6), and a row
    that somehow carries one is left out rather than renumbered.
    """
    rows = list(
        FetchAttempt.objects.filter(url=url, rung__lte=9).order_by("-created_at")[:10]
    )
    steps: list[dict[str, object]] = []
    for row in reversed(rows):
        reason = f"HTTP {row.status_code}: {row.reason}" if row.status_code else row.reason
        steps.append(
            {
                "vendor": row.vendor[:20],
                "rung": row.rung,
                "outcome": row.outcome[:20],
                "reason": reason[:300],
                "at": row.created_at.isoformat(),
            }
        )
    return steps


def file_host_unreachable(
    url: str, reason: str, trail: Sequence[Mapping[str, object]] | None = None
) -> ResolutionItem | None:
    """File (or refresh) "we could not open this host -- where is the page now?".

    The pipeline's one queue writer (plan Task 9), for a lead the whole ladder
    refused as BLOCKED, UNREACHABLE or UNREADABLE, or one the vendor rendered
    into an empty shell. Keyed by the full lowercased hostname, so every
    tenant's run that meets the host is one item. `trail` defaults to the
    URL's own FetchAttempt history.

    Files nothing when the question is already answered: a `MovedPage` for the
    URL (an operator's paste) or a retired host (an operator's "closed").
    Those are exactly what `retrieve_official_source` reads before fetching,
    so a refusal after either is not this question.
    """
    canonical = canonicalize_url(url)
    host = (urlsplit(canonical).hostname or "").lower()
    if MovedPage.objects.filter(from_url=canonical).exists():
        return None
    if HostProfile.objects.filter(host=host, retired_at__isnull=False).exists():
        return None
    subject = f"host:{host}"
    evidence: dict[str, object] = {
        "host": host,
        "url": canonical,
        "trail": list(trail) if trail is not None else _trail(canonical),
        "why": reason[:300],
    }
    country_code, registered = subject_facts(subject, evidence)
    return file_item(
        "HOST_UNREACHABLE", subject, evidence, country_code=country_code, registered=registered
    )


def withdraw_host_unreachable(url: str) -> bool:
    """The host answered on its own: withdraw its OPEN or PARKED item."""
    host = (urlsplit(url).hostname or "").lower()
    return bool(host) and withdraw_item("HOST_UNREACHABLE", f"host:{host}")


def sync_award_dispute(row: FundingOpportunity, snapshot: OfficialSourceSnapshot) -> None:
    """The funding reader's one call, after every row it writes.

    Files when the row needs a person; withdraws an OPEN or PARKED item when
    the machine or the page answered it (served, suspended, withdrawn); leaves
    an ABSTAINED row's question standing, since a failed reading answered
    nothing. Runs inside the writer's own transaction, as its role."""
    if award_needs_a_person(row):
        file_award_dispute(row, snapshot)
    elif row.agreement != "ABSTAINED":
        withdraw_item("AWARD_DISPUTED", award_subject(row))
