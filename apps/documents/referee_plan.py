"""Who writes for which application (lanes spec §11.2). Pure: needs and referees in,
a proposal out; the page writes it as PROPOSED RefereeRequest rows.

Rules, in the spec's order:
- each application gets its `letters`, from distinct referees of its `kind`;
- a referee's PORTAL_INVITE and REFEREE_SENDS requests stay within `agreed_requests`
  (an unstated mode counts too: it may be a portal invitation, and a professor is
  never asked for more than they agreed to);
- a generic letter serves every UPLOAD_GENERIC application at no cost;
- the strongest referee goes first to funding-deciding applications, then to the
  earliest deadlines;
- an institutional address is preferred where one is required, and flagged when
  the referee given has none.

"Strongest", from what is stored: an academic referee before a professional one,
then the one who agreed to more requests, then by name so the result is stable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

#: The modes that cost one of a referee's agreed requests.
_UPLOADS = frozenset({"UPLOAD_GENERIC", "UPLOAD_ADDRESSED"})
_ORDINALS = ("first", "second", "third", "fourth", "fifth")


def costs_a_request(mode: str) -> bool:
    return mode not in _UPLOADS


@dataclass(frozen=True)
class ApplicationNeed:
    application_id: UUID
    title: str
    #: None when the page does not say how many: nothing is proposed for it.
    letters: int | None
    #: ACADEMIC, PROFESSIONAL, EITHER, or "" (not stated: anyone).
    kind: str = ""
    #: The referee mode copied from the requirement, or "" (not stated).
    mode: str = ""
    institutional_email: bool = False
    deadline: datetime | None = None
    funding_deciding: bool = False


@dataclass(frozen=True)
class RefereeFacts:
    referee_id: UUID
    #: How the student names them: "Prof. Aliyev".
    name: str
    kind: str
    agreed_requests: int
    gives_generic_letter: bool = False
    institutional_email: bool = False


@dataclass(frozen=True)
class Assignment:
    application_id: UUID
    referee_id: UUID
    mode: str
    #: Institutional address required, and this referee's is not one.
    email_flag: bool = False


@dataclass(frozen=True)
class Proposal:
    assignments: tuple[Assignment, ...]
    #: The "too few" sentences, in the spec's shape.
    short: tuple[str, ...] = ()
    #: Applications whose page does not say how many letters.
    unstated: tuple[UUID, ...] = ()


@dataclass
class _Load:
    used: int = 0
    on: set[UUID] = field(default_factory=set)


def _strength(referee: RefereeFacts) -> tuple[bool, int, str]:
    return (referee.kind != "ACADEMIC", -referee.agreed_requests, referee.name)


def _fits(referee: RefereeFacts, need: ApplicationNeed) -> bool:
    return need.kind in ("", "EITHER") or referee.kind == need.kind


def _order(need: ApplicationNeed) -> tuple[bool, bool, datetime]:
    return (not need.funding_deciding, need.deadline is None, need.deadline or datetime.max)


def _cost(need: ApplicationNeed, referee: RefereeFacts) -> int:
    """One agreed request, unless the letter is an upload: a generic letter is free
    only from a professor who gives one."""
    if costs_a_request(need.mode):
        return 1
    return int(need.mode == "UPLOAD_GENERIC" and not referee.gives_generic_letter)


def propose(
    needs: Sequence[ApplicationNeed],
    referees: Sequence[RefereeFacts],
    *,
    kept: Sequence[Assignment] = (),
    declined: Sequence[tuple[UUID, UUID]] = (),
) -> Proposal:
    """`kept` are requests already ASKED, AGREED or SUBMITTED: they fill their slots
    and use their referee's requests before anything new is proposed. A kept request
    whose referee is not in `referees` (a submitted letter from a professor since
    marked silent) still fills its slot. `declined` are (application id, referee id)
    pairs a professor already said no to: never proposed again.

    Greedy in priority order, then each slot still empty is repaired with an
    augmenting path (move an earlier pick to another capable professor), so "short"
    is reported only when no full assignment exists."""
    blocked = set(declined)
    by_id = {r.referee_id: r for r in referees}
    load = {referee.referee_id: _Load() for referee in referees}
    by_app = {need.application_id: need for need in needs}
    away: dict[UUID, int] = {}
    for done in kept:
        owed = by_app.get(done.application_id)
        if done.referee_id in load:
            load[done.referee_id].on.add(done.application_id)
            if owed is not None:
                load[done.referee_id].used += _cost(owed, by_id[done.referee_id])
            elif costs_a_request(done.mode):
                load[done.referee_id].used += 1
        else:
            away[done.application_id] = away.get(done.application_id, 0) + 1
    strongest = sorted(referees, key=_strength)
    made: list[Assignment] = []

    def have(need: ApplicationNeed) -> int:
        return away.get(need.application_id, 0) + sum(
            1 for r in load.values() if need.application_id in r.on
        )

    def capable(r: RefereeFacts, need: ApplicationNeed) -> bool:
        return (
            _fits(r, need)
            and need.application_id not in load[r.referee_id].on
            and (need.application_id, r.referee_id) not in blocked
        )

    def give(need: ApplicationNeed, r: RefereeFacts) -> Assignment:
        load[r.referee_id].used += _cost(need, r)
        load[r.referee_id].on.add(need.application_id)
        row = Assignment(
            need.application_id, r.referee_id, need.mode,
            email_flag=need.institutional_email and not r.institutional_email,
        )
        made.append(row)
        return row

    def take_back(a: Assignment) -> None:
        r, need = by_id[a.referee_id], by_app[a.application_id]
        load[r.referee_id].used -= _cost(need, r)
        load[r.referee_id].on.discard(a.application_id)
        made.remove(a)

    def augment(need: ApplicationNeed, seen: set[UUID]) -> bool:
        for r in strongest:
            if r.referee_id in seen or not capable(r, need):
                continue
            seen.add(r.referee_id)
            cost = _cost(need, r)
            if load[r.referee_id].used + cost <= r.agreed_requests:
                give(need, r)
                return True
            for a in [m for m in made if m.referee_id == r.referee_id]:
                other = by_app[a.application_id]
                freed = _cost(other, r)
                if load[r.referee_id].used - freed + cost > r.agreed_requests:
                    continue
                take_back(a)
                row = give(need, r)
                if augment(other, seen):
                    return True
                made.remove(row)  # exactly give()'s row: a failed deeper repair appended others
                load[r.referee_id].used -= cost
                load[r.referee_id].on.discard(need.application_id)
                made.append(a)
                load[r.referee_id].used += freed
                load[r.referee_id].on.add(a.application_id)
        return False

    short_apps: list[ApplicationNeed] = []
    unstated = []
    ordered = sorted(needs, key=_order)
    for need in ordered:
        if need.letters is None:
            unstated.append(need.application_id)
            continue
        candidates = sorted(
            (r for r in strongest if capable(r, need)),
            key=lambda r: (
                not (need.mode == "UPLOAD_GENERIC" and r.gives_generic_letter),
                not (need.institutional_email and r.institutional_email),
                _strength(r),
            ),
        )
        for referee in candidates:
            if have(need) >= need.letters:
                break
            if load[referee.referee_id].used + _cost(need, referee) > referee.agreed_requests:
                continue
            give(need, referee)
    for need in ordered:
        if need.letters is None:
            continue
        while have(need) < need.letters and augment(need, set()):
            pass
        if have(need) < need.letters:
            short_apps.append(need)
    return Proposal(tuple(made), _short(short_apps, needs, referees), tuple(unstated))


def _short(
    short_apps: Sequence[ApplicationNeed],
    needs: Sequence[ApplicationNeed],
    referees: Sequence[RefereeFacts],
) -> tuple[str, ...]:
    if not short_apps:
        return ()
    if not referees:
        total = sum(n.letters or 0 for n in needs)
        plural = "s" if total != 1 else ""
        return (
            f"Your pack needs {total} letter{plural}. Add the professors who will write for you.",
        )
    lines = []
    portal = [n for n in needs if n.letters and costs_a_request(n.mode)]
    needed = sum(n.letters or 0 for n in portal)
    agreed = sum(r.agreed_requests for r in referees)
    if any(costs_a_request(n.mode) for n in short_apps) and needed > agreed:
        willing = [r for r in referees if r.agreed_requests] or list(referees)
        who = (
            f"{willing[0].name} agreed to {agreed}" if len(willing) == 1
            else f"Your referees agreed to {agreed}"
        )
        ordinal = f"a {_ORDINALS[len(referees)]}" if len(referees) < len(_ORDINALS) else "another"
        kinds = {n.kind for n in short_apps if costs_a_request(n.mode)}
        word = {"ACADEMIC": "academic ", "PROFESSIONAL": "professional "}.get(
            kinds.pop() if len(kinds) == 1 else "", ""
        )
        line = (
            f"{who}; your pack needs {needed} portal letter{'s' if needed != 1 else ''}. "
            f"Ask {ordinal} {word}referee"
        )
        uploads = sum(1 for n in needs if n.mode == "UPLOAD_GENERIC")
        generic = [r for r in referees if r.gives_generic_letter]
        if uploads and generic:
            whose = f"{generic[0].name}'s" if len(generic) == 1 else "a"
            line += (
                f", or the {uploads} programme{'s' if uploads > 1 else ''} that accept"
                f"{'' if uploads > 1 else 's'} an uploaded letter can use {whose} generic one"
            )
        lines.append(line + ".")
    for need in short_apps:
        if costs_a_request(need.mode) and needed > agreed:
            continue
        kind = {"ACADEMIC": "academic ", "PROFESSIONAL": "professional "}.get(need.kind, "")
        many = (need.letters or 0) > 1
        lines.append(
            f"{need.title} needs {need.letters} {kind}letter{'s' if need.letters != 1 else ''}"
            f"{' from different referees' if many else ''}. Add another {kind}referee."
        )
    return tuple(lines)
