"""A newer CV replaces the facts it restates (spec 2026-10-12 §4).

Before this, every upload wrote one candidate row per entry, so a second CV
duplicated every fact. A changed date then made two confirmed facts disagree,
the verifier read CONFLICTING, and the draft was blocked with nothing the
student could do about it.

An entry is matched to a supersession chain by category and identity -- the
verifier's own identity (verification.fact_identity) -- against EVERY row of
the chain, not only its tip. The tip alone is not enough: a student who
corrected "B.Sc. of Chem. Eng." would otherwise see the abbreviation come back
as a second degree on the next upload.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import Membership

from .audit import record_event
from .confirmation import confirm_facts
from .models import VerifiedFact
from .verification import _fact_payload as _payload
from .verification import fact_identity, unsuperseded_facts

#: The prefix ingest_uploaded_cv stamps on every row it writes.
UPLOAD_REF_PREFIX = "upload:"


@dataclass(frozen=True)
class Chain:
    tip: VerifiedFact
    #: The tip first, then every row it superseded, newest to oldest.
    rows: tuple[VerifiedFact, ...]


@dataclass(frozen=True)
class Write:
    payload: dict[str, object]
    #: The tip this row replaces, or None for an entry only the new CV has.
    supersedes: VerifiedFact | None


def _empty(value: object) -> bool:
    return value is None or value == "" or value == [] or value == {}


def chains(student: Membership, category: str) -> list[Chain]:
    """Every supersession chain of one category, newest tip first."""
    rows = list(
        VerifiedFact.objects.filter(student=student, category=category).order_by(
            "-created_at", "-id"
        )
    )
    by_id = {row.id: row for row in rows}
    superseded = {row.supersedes_id for row in rows if row.supersedes_id is not None}
    found: list[Chain] = []
    for tip in rows:
        if tip.id in superseded:
            continue
        members = [tip]
        while members[-1].supersedes_id in by_id:
            members.append(by_id[members[-1].supersedes_id])
        found.append(Chain(tip=tip, rows=tuple(members)))
    return found


def merged_payload(chain: Chain, new: Mapping[str, object]) -> dict[str, object]:
    """The tip, with only what the new CV says differently AND newly.

    A blank is never a change: a CV that leaves out a city has not said the
    city changed. A value an older row of this chain already held is never a
    change either: the chain moved away from it, so the new CV is repeating a
    superseded value.
    """
    merged = dict(_payload(chain.tip))
    for key, value in new.items():
        if _empty(value) or value == merged.get(key):
            continue
        if any(_payload(row).get(key) == value for row in chain.rows[1:]):
            continue
        merged[key] = value
    return merged


def _match(category: str, payload: Mapping[str, object], open_chains: list[Chain]) -> Chain | None:
    if category == VerifiedFact.Category.IDENTITY:
        # One person per ledger: a re-spelled name is a change to show, not a
        # second identity. Prefer the non-authoritative CV identity chain over
        # per-key AUTHORITATIVE_DOCUMENT passport rows so CV contact updates
        # are not silently skipped.
        return next(
            (
                c
                for c in open_chains
                if c.tip.source_tier != VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
            ),
            open_chains[0] if open_chains else None,
        )
    identity = fact_identity(category, payload)
    if not any(identity):
        return None
    candidates = [
        chain
        for chain in open_chains
        if any(fact_identity(category, _payload(row)) == identity for row in chain.rows)
    ]
    # Two posts can share an identity (same employer and title); the start
    # date tells them apart when it did not change.
    return next(
        (c for c in candidates if _payload(c.tip).get("start_date") == payload.get("start_date")),
        candidates[0] if candidates else None,
    )


def plan_upload(
    category: str, payloads: Sequence[dict[str, object]], existing: list[Chain]
) -> list[Write]:
    """What one category of a newly read CV writes, in document order.

    Each chain is claimed at most once, so two posts sharing an identity match
    two chains. An AUTHORITATIVE_DOCUMENT tip is read off a document and is
    never overwritten by a CV.
    """
    open_chains = list(existing)
    writes: list[Write] = []
    for payload in payloads:
        chain = _match(category, payload, open_chains)
        if chain is None:
            writes.append(Write(payload=payload, supersedes=None))
            continue
        open_chains = [other for other in open_chains if other is not chain]
        if chain.tip.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT:
            continue
        merged = merged_payload(chain, payload)
        if merged != _payload(chain.tip):
            writes.append(Write(payload=merged, supersedes=chain.tip))
    return writes


@dataclass(frozen=True)
class PendingChange:
    #: The unconfirmed row the newer CV wrote.
    fact: VerifiedFact
    #: The newest row of the same chain the student confirmed: what "keep the
    #: old value" restores, and what "old" means on the page.
    kept: VerifiedFact
    #: (payload key, old value, new value), in the new row's key order.
    changes: tuple[tuple[str, object, object], ...]


def pending_changes(student: Membership) -> list[PendingChange]:
    """Every upload row waiting for the student to accept or decline it.

    Pending means: an unconfirmed tip written by an upload, whose chain holds a
    confirmed row. A change to a never-confirmed candidate is not pending -- it
    replaces a value nobody stood behind and joins the ordinary candidate list.
    """
    tips = unsuperseded_facts(student).filter(
        confirmed_by__isnull=True, source_ref__startswith=UPLOAD_REF_PREFIX
    )
    found: list[PendingChange] = []
    for category in {tip.category for tip in tips}:
        for chain in chains(student, category):
            tip = chain.tip
            if tip.confirmed_by_id is not None or not tip.source_ref.startswith(
                UPLOAD_REF_PREFIX
            ):
                continue
            kept = next((row for row in chain.rows[1:] if row.confirmed_by_id is not None), None)
            if kept is None:
                continue
            old, new = _payload(kept), _payload(tip)
            changes = tuple(
                (key, old.get(key), value) for key, value in new.items() if value != old.get(key)
            )
            found.append(PendingChange(fact=tip, kept=kept, changes=changes))
    return sorted(found, key=lambda change: (change.fact.created_at, change.fact.id))


def has_pending_changes(student: Membership) -> bool:
    return bool(pending_changes(student))


@transaction.atomic
def settle_changes(
    *,
    student: Membership,
    shown: Iterable[UUID],
    accepted: Iterable[UUID],
    actor: Membership,
) -> tuple[int, int]:
    """The student's one press: ticked changes are confirmed, unticked ones are
    declined by a confirmed row that restores the old payload.

    Only ids that were SHOWN and are STILL pending are touched. A change that
    arrived after the page was rendered stays pending rather than being
    declined unseen. A replayed or forged id is not pending and is ignored.

    A concurrent second press can still race to supersede the same row; the
    verifiedfact_one_superseder index refuses it and the IntegrityError
    propagates for the view to report.
    """
    pending = {change.fact.id: change for change in pending_changes(student)}
    shown_ids = set(shown) & set(pending)
    accepted_ids = set(accepted) & shown_ids
    if accepted_ids:
        confirm_facts(student=student, fact_ids=accepted_ids, actor=actor)
    declined = sorted(shown_ids - accepted_ids)
    now = timezone.now()
    for fact_id in declined:
        change = pending[fact_id]
        restored = VerifiedFact.objects.create(
            student=student,
            category=change.kept.category,
            payload=dict(_payload(change.kept)),
            source_tier=change.kept.source_tier,
            # The old row's provenance, not ours: this row IS the old claim, and
            # gaps._already_created finds a gap-created fact by this stamp.
            source_ref=change.kept.source_ref,
            confirmed_by=actor,
            confirmed_at=now,
            supersedes=change.fact,
            created_by=actor,
        )
        record_event(actor=actor, event="fact.change_declined", object_id=restored.id)
    return len(accepted_ids), len(declined)
