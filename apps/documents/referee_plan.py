"""Who writes for which application (lanes spec §11.2). Pure: needs and referees in,
a proposal out; the page writes it as PROPOSED RefereeRequest rows.

Formulated as a lexicographic Submodular Welfare Maximization with Separable
Convex Load Penalties reduced to Integer Minimum-Cost Maximum Flow (Minoux
1986; Lian et al., AAAI 2018; Ahmadi et al., IJCAI 2020; Leyton-Brown et al.,
Artificial Intelligence 2024):
- each application gets its `letters`, from distinct referees of its `kind`
  (and respecting `min_academic` and `webmail_blocked` when stated);
- a referee's PORTAL_INVITE and REFEREE_SENDS requests stay within `agreed_requests`
  (an unstated mode counts too: it may be a portal invitation, and a professor is
  never asked for more than they agreed to);
- a generic letter serves every UPLOAD_GENERIC application at no cost;
- the strongest referee (academic, research supervisor / shared work, higher agreed
  requests) goes first to funding-deciding applications, then to earliest deadlines;
- multi-letter applications prefer complementary referee role archetypes
  (research_supervisor + course_instructor / professional_supervisor);
- paid portal requests are load-balanced across equally qualified referees via
  strictly convex marginal load costs;
- an institutional address is preferred where one is required, and flagged only when
  no zero-flag assignment of maximum cardinality exists.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

#: The modes that do not cost one of a referee's agreed requests.
_UPLOADS = frozenset({"UPLOAD_GENERIC"})
_ORDINALS = ("first", "second", "third", "fourth", "fifth")

RoleArchetype = Literal[
    "research_supervisor",
    "course_instructor",
    "professional_supervisor",
    "",
]


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
    #: Optional minimum number of ACADEMIC referees required when kind in ("", "EITHER").
    min_academic: int = 0
    #: Optional hard block on non-institutional (webmail) addresses.
    webmail_blocked: bool = False


@dataclass(frozen=True)
class RefereeFacts:
    referee_id: UUID
    #: How the student names them: "Prof. Aliyev".
    name: str
    kind: str
    agreed_requests: int
    gives_generic_letter: bool = False
    institutional_email: bool = False
    #: Optional role archetype from referee_evidence.classify_referee_role.
    role_archetype: RoleArchetype = ""
    #: Optional shared-work evidence count from referee_evidence.shared_work_for_referee.
    shared_work_score: int = 0


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


def _effective_role(referee: RefereeFacts) -> str:
    if referee.role_archetype:
        return referee.role_archetype
    if referee.kind == "PROFESSIONAL":
        return "professional_supervisor"
    if referee.shared_work_score > 0:
        return "research_supervisor"
    return "academic_general"


def _strength(referee: RefereeFacts) -> tuple[bool, int, int, int, str]:
    return (
        referee.kind != "ACADEMIC",
        -(1 if referee.role_archetype == "research_supervisor" else 0),
        -max(0, int(referee.shared_work_score)),
        -max(0, int(referee.agreed_requests)),
        referee.name,
    )


def _fits(referee: RefereeFacts, need: ApplicationNeed) -> bool:
    if need.webmail_blocked and not referee.institutional_email:
        return False
    return need.kind in ("", "EITHER") or referee.kind == need.kind


def _order(need: ApplicationNeed) -> tuple[bool, bool, datetime]:
    return (
        not need.funding_deciding,
        need.deadline is None,
        need.deadline or datetime.max,
    )


def _cost(need: ApplicationNeed, referee: RefereeFacts) -> int:
    """One agreed request, unless the letter is an upload: a generic letter is free
    only from a professor who gives one."""
    if costs_a_request(need.mode):
        return 1
    return int(need.mode == "UPLOAD_GENERIC" and not referee.gives_generic_letter)


class _Edge:
    __slots__ = ("to", "rev", "cap", "cost")

    def __init__(self, to: int, rev: int, cap: int, cost: int) -> None:
        self.to = to
        self.rev = rev
        self.cap = cap
        self.cost = cost


class _MinCostMaxFlow:
    """Pure-Python Successive Shortest Augmenting Path (SPFA) MCMF solver."""

    def __init__(self, n_nodes: int) -> None:
        self.n = n_nodes
        self.graph: list[list[_Edge]] = [[] for _ in range(n_nodes)]

    def add_edge(self, u: int, v: int, cap: int, cost: int) -> _Edge:
        fwd = _Edge(v, len(self.graph[v]), cap, cost)
        rev = _Edge(u, len(self.graph[u]), 0, -cost)
        self.graph[u].append(fwd)
        self.graph[v].append(rev)
        return fwd

    def max_flow_min_cost(self, src: int, snk: int) -> tuple[int, int]:
        total_flow = 0
        total_cost = 0
        inf = 10**18
        n = self.n
        graph = self.graph

        while True:
            dist = [inf] * n
            parent_node = [-1] * n
            parent_edge = [-1] * n
            in_queue = [False] * n

            dist[src] = 0
            queue: deque[int] = deque([src])
            in_queue[src] = True

            while queue:
                u = queue.popleft()
                in_queue[u] = False
                du = dist[u]
                for idx, e in enumerate(graph[u]):
                    if e.cap > 0 and du + e.cost < dist[e.to]:
                        v = e.to
                        dist[v] = du + e.cost
                        parent_node[v] = u
                        parent_edge[v] = idx
                        if not in_queue[v]:
                            queue.append(v)
                            in_queue[v] = True

            if dist[snk] == inf:
                break

            push = inf
            v = snk
            while v != src:
                u = parent_node[v]
                e = graph[u][parent_edge[v]]
                if e.cap < push:
                    push = e.cap
                v = u

            v = snk
            while v != src:
                u = parent_node[v]
                e = graph[u][parent_edge[v]]
                e.cap -= push
                graph[v][e.rev].cap += push
                v = u

            total_flow += push
            total_cost += push * dist[snk]

        return total_flow, total_cost


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

    Solved globally via Integer Minimum-Cost Maximum Flow (Successive Shortest
    Augmenting Paths) with role-complementarity split buckets and convex load
    penalties, so 'short' is reported only when no full assignment exists and
    augmenting paths never degrade higher-priority or institutional-email slots."""
    blocked = set(declined)
    by_id = {r.referee_id: r for r in referees}
    used = {r.referee_id: 0 for r in referees}
    on_app: dict[UUID, set[UUID]] = {n.application_id: set() for n in needs}
    by_app = {need.application_id: need for need in needs}
    away: dict[UUID, int] = {}

    for done in kept:
        owed = by_app.get(done.application_id)
        if done.referee_id in used:
            if done.application_id in on_app:
                on_app[done.application_id].add(done.referee_id)
            if owed is not None:
                used[done.referee_id] += _cost(owed, by_id[done.referee_id])
            elif costs_a_request(done.mode):
                used[done.referee_id] += 1
        else:
            away[done.application_id] = away.get(done.application_id, 0) + 1

    strongest = sorted(referees, key=_strength)
    ref_rank = {r.referee_id: idx for idx, r in enumerate(strongest)}

    ordered = sorted(needs, key=_order)
    unstated: list[UUID] = []
    active_needs: list[tuple[int, ApplicationNeed, int]] = []

    for rank_idx, need in enumerate(ordered):
        if need.letters is None:
            unstated.append(need.application_id)
            continue
        have_count = away.get(need.application_id, 0) + len(on_app[need.application_id])
        rem = max(0, need.letters - have_count)
        if rem > 0:
            active_needs.append((rank_idx, need, rem))

    if not active_needs or not strongest:
        return Proposal(
            (),
            _short([need for _idx, need, _rem in active_needs], needs, referees),
            tuple(unstated),
        )

    # Build Min-Cost Max-Flow network
    src = 0
    snk = 1
    next_node = 2

    paid_node: dict[UUID, int] = {}
    free_node: dict[UUID, int] = {}
    for r in strongest:
        paid_node[r.referee_id] = next_node
        free_node[r.referee_id] = next_node + 1
        next_node += 2

    prog_node: dict[UUID, int] = {}
    acad_node: dict[UUID, int] = {}
    other_node: dict[UUID, int] = {}
    role_node: dict[tuple[UUID, str, str], int] = {}

    for _rank_idx, need, _rem in active_needs:
        app_id = need.application_id
        prog_node[app_id] = next_node
        acad_node[app_id] = next_node + 1
        other_node[app_id] = next_node + 2
        next_node += 3
        for r in strongest:
            bkey = (app_id, r.kind, _effective_role(r))
            if bkey not in role_node:
                role_node[bkey] = next_node
                next_node += 1

    mcmf = _MinCostMaxFlow(next_node)
    n_active = len(active_needs)

    # 1. Supply arcs from SRC to referee paid/free nodes
    for r in strongest:
        rid = r.referee_id
        kept_used = used[rid]
        agreed_req = max(0, int(r.agreed_requests))
        rem_quota = max(0, agreed_req - kept_used)
        # Parallel unit-capacity arcs with strictly increasing convex marginal cost
        for ell in range(rem_quota):
            load_step = kept_used + ell + 1
            marginal_load_cost = 10 * load_step + (
                10 * load_step // max(1, agreed_req)
            )
            mcmf.add_edge(src, paid_node[rid], 1, marginal_load_cost)

        # Free upload node is open iff referee is not over their agreed_requests
        if kept_used <= agreed_req:
            mcmf.add_edge(src, free_node[rid], n_active, 0)

    # 2. Programme-to-sink and role/kind bucket arcs
    pair_edges: list[tuple[ApplicationNeed, RefereeFacts, _Edge]] = []
    num_ordered = max(1, len(ordered))
    has_explicit_roles = any(
        r.role_archetype != "" or r.shared_work_score > 0 for r in strongest
    )

    for rank_idx, need, rem in active_needs:
        app_id = need.application_id
        # Priority weight Pi_p: funding_deciding first, then earlier deadlines
        pi_p = (
            100
            + (120 if need.funding_deciding else 0)
            + max(0, (num_ordered - rank_idx) * 4)
        )

        kept_acad = sum(
            1 for rid in on_app[app_id] if rid in by_id and by_id[rid].kind == "ACADEMIC"
        )
        req_acad_rem = max(0, min(rem, need.min_academic - kept_acad))
        max_other = max(0, rem - req_acad_rem)

        mcmf.add_edge(acad_node[app_id], prog_node[app_id], rem, 0)
        if max_other > 0:
            mcmf.add_edge(other_node[app_id], prog_node[app_id], max_other, 0)
        mcmf.add_edge(prog_node[app_id], snk, rem, 0)

        kept_roles = {
            _effective_role(by_id[rid]) for rid in on_app[app_id] if rid in by_id
        }
        role_bonus = (60 * pi_p) if has_explicit_roles else 0

        seen_buckets: set[tuple[UUID, str, str]] = set()
        for r in strongest:
            bkey = (app_id, r.kind, _effective_role(r))
            if bkey in seen_buckets:
                continue
            seen_buckets.add(bkey)
            rnode = role_node[bkey]
            target_kind = acad_node[app_id] if r.kind == "ACADEMIC" else other_node[app_id]
            first_delta = -role_bonus if _effective_role(r) not in kept_roles else 0
            mcmf.add_edge(rnode, target_kind, 1, first_delta)
            if rem > 1:
                mcmf.add_edge(rnode, target_kind, rem - 1, 0)

        for r in strongest:
            rid = r.referee_id
            if (
                not _fits(r, need)
                or rid in on_app[app_id]
                or (app_id, rid) in blocked
            ):
                continue
            cost_req = _cost(need, r)
            sup_node = paid_node[rid] if cost_req else free_node[rid]
            rnode = role_node[(app_id, r.kind, _effective_role(r))]

            slot_reward = 100_000 * pi_p
            generic_pref = (
                8_000 * pi_p
                if (need.mode == "UPLOAD_GENERIC" and r.gives_generic_letter)
                else 0
            )
            email_penalty = (
                4_000 * pi_p
                if (need.institutional_email and not r.institutional_email)
                else 0
            )
            strength_bonus = pi_p * (
                (500 if r.kind == "ACADEMIC" else 0)
                + 25 * min(max(0, int(r.shared_work_score)), 5)
                + (20 if r.role_archetype == "research_supervisor" else 0)
                + min(max(0, int(r.agreed_requests)), 20)
            )
            tie_break = ref_rank[rid]

            edge_cost = (
                -(slot_reward + generic_pref + strength_bonus - email_penalty)
                + tie_break
            )
            edge = mcmf.add_edge(sup_node, rnode, 1, edge_cost)
            pair_edges.append((need, r, edge))

    mcmf.max_flow_min_cost(src, snk)

    made: list[Assignment] = []
    filled_new: dict[UUID, int] = {n.application_id: 0 for n in needs}

    for need, r, edge in pair_edges:
        if edge.cap == 0:
            filled_new[need.application_id] += 1
            made.append(
                Assignment(
                    need.application_id,
                    r.referee_id,
                    need.mode,
                    email_flag=need.institutional_email and not r.institutional_email,
                )
            )

    short_apps: list[ApplicationNeed] = []
    for _rank_idx, need, rem in active_needs:
        if filled_new[need.application_id] < rem:
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
    has_generic_referee = any(r.gives_generic_letter for r in referees)

    def _need_costs_request(n: ApplicationNeed) -> bool:
        if costs_a_request(n.mode):
            return True
        return bool(n.mode == "UPLOAD_GENERIC" and not has_generic_referee)

    portal = [n for n in needs if n.letters and _need_costs_request(n)]
    needed = sum(n.letters or 0 for n in portal)
    agreed = sum(max(0, int(r.agreed_requests)) for r in referees)
    if any(_need_costs_request(n) for n in short_apps) and needed > agreed:
        willing = [r for r in referees if max(0, int(r.agreed_requests))] or list(referees)
        who = (
            f"{willing[0].name} agreed to {agreed}" if len(willing) == 1
            else f"Your referees agreed to {agreed}"
        )
        ordinal = f"a {_ORDINALS[len(referees)]}" if len(referees) < len(_ORDINALS) else "another"
        kinds = {n.kind for n in short_apps if _need_costs_request(n)}
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
        if _need_costs_request(need) and needed > agreed:
            continue
        kind = {"ACADEMIC": "academic ", "PROFESSIONAL": "professional "}.get(need.kind, "")
        many = (need.letters or 0) > 1
        lines.append(
            f"{need.title} needs {need.letters} {kind}letter{'s' if need.letters != 1 else ''}"
            f"{' from different referees' if many else ''}. Add another {kind}referee."
        )
    return tuple(lines)
