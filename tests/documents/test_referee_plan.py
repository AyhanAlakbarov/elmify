import random
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from apps.documents.referee_plan import (
    ApplicationNeed,
    Assignment,
    Proposal,
    RefereeFacts,
    propose,
)

ALIYEV, KARIMOVA, HASANOV = (uuid4() for _ in range(3))


def _app(
    title: str,
    letters: int | None,
    mode: str = "PORTAL_INVITE",
    *,
    kind: str = "",
    day: int = 1,
    funding: bool = False,
    email: bool = False,
) -> ApplicationNeed:
    return ApplicationNeed(
        application_id=uuid4(), title=title, letters=letters, kind=kind, mode=mode,
        institutional_email=email, deadline=datetime(2027, 1, day, tzinfo=UTC),
        funding_deciding=funding,
    )


def _ref(
    id_: UUID,
    name: str,
    kind: str = "ACADEMIC",
    agreed: int = 3,
    generic: bool = False,
    institutional: bool = True,
) -> RefereeFacts:
    return RefereeFacts(id_, name, kind, agreed, generic, institutional)


def _who(proposal: Proposal, need: ApplicationNeed) -> set[UUID]:
    return {a.referee_id for a in proposal.assignments if a.application_id == need.application_id}


def test_every_application_gets_its_count_from_distinct_referees() -> None:
    tum, lund = _app("TUM", 2), _app("Lund", 1)
    proposal = propose([tum, lund], [_ref(ALIYEV, "Prof. Aliyev"), _ref(KARIMOVA, "Dr. Karimova")])
    assert _who(proposal, tum) == {ALIYEV, KARIMOVA}
    assert len(_who(proposal, lund)) == 1
    assert proposal.short == ()


def test_a_professor_who_agreed_to_none_gets_no_portal_request_but_may_upload() -> None:
    portal, upload = _app("TUM", 1), _app("Lund", 1, "UPLOAD_GENERIC")
    proposal = propose(
        [portal, upload], [_ref(KARIMOVA, "Dr. Karimova", agreed=0, generic=True)]
    )
    assert _who(proposal, portal) == set()
    assert _who(proposal, upload) == {KARIMOVA}
    assert proposal.short == (
        "Dr. Karimova agreed to 0; your pack needs 1 portal letter. Ask a second referee, "
        "or the 1 programme that accepts an uploaded letter can use Dr. Karimova's generic one.",
    )


def test_uploads_never_use_up_agreed_requests() -> None:
    uploads = [_app(f"P{i}", 1, "UPLOAD_GENERIC") for i in range(4)]
    proposal = propose(uploads, [_ref(ALIYEV, "Prof. Aliyev", agreed=1, generic=True)])
    assert len(proposal.assignments) == 4 and proposal.short == ()


def test_a_generic_letter_giver_is_preferred_for_generic_uploads() -> None:
    upload = _app("Lund", 1, "UPLOAD_GENERIC")
    proposal = propose(
        [upload], [_ref(ALIYEV, "Prof. Aliyev"), _ref(HASANOV, "Prof. Zeynalov", generic=True)]
    )
    assert _who(proposal, upload) == {HASANOV}


def test_the_strongest_goes_to_funding_then_to_the_earliest_deadline() -> None:
    late_funding = _app("DAAD", 1, day=20, funding=True)
    early = _app("TUM", 1, day=2)
    later = _app("Lund", 1, day=10)
    proposal = propose(
        [later, early, late_funding],
        [_ref(ALIYEV, "Prof. Aliyev", agreed=2), _ref(HASANOV, "Mr. Hasanov", "PROFESSIONAL", 5)],
    )
    assert _who(proposal, late_funding) == {ALIYEV}
    assert _who(proposal, early) == {ALIYEV}
    assert _who(proposal, later) == {HASANOV}


def test_kind_is_met_and_a_missing_kind_is_named() -> None:
    academic = _app("ETH", 2, kind="ACADEMIC")
    proposal = propose(
        [academic], [_ref(ALIYEV, "Prof. Aliyev"), _ref(HASANOV, "Mr. Hasanov", "PROFESSIONAL")]
    )
    assert _who(proposal, academic) == {ALIYEV}
    assert proposal.short == (
        "ETH needs 2 academic letters from different referees. Add another academic referee.",
    )


def test_an_institutional_address_is_preferred_and_its_absence_flagged() -> None:
    strict = _app("KTH", 1, email=True)
    both = propose([strict], [
        _ref(ALIYEV, "Prof. Aliyev", agreed=9, institutional=False),
        _ref(KARIMOVA, "Dr. Karimova", agreed=1),
    ])
    assert both.assignments == (Assignment(strict.application_id, KARIMOVA, "PORTAL_INVITE"),)
    only_gmail = propose([strict], [_ref(ALIYEV, "Prof. Aliyev", institutional=False)])
    assert only_gmail.assignments[0].email_flag is True


def test_too_few_in_the_spec_s_shape() -> None:
    needs = [
        _app("TUM", 2), _app("KTH", 2), _app("ETH", 1, "REFEREE_SENDS"),
        _app("Lund", 1, "UPLOAD_GENERIC"), _app("Aalto", 1, "UPLOAD_GENERIC"),
    ]
    proposal = propose(needs, [
        _ref(ALIYEV, "Prof. Aliyev", agreed=3, generic=True),
        _ref(KARIMOVA, "Dr. Karimova", agreed=0),
    ])
    assert proposal.short[0] == (
        "Prof. Aliyev agreed to 3; your pack needs 5 portal letters. Ask a third referee, "
        "or the 2 programmes that accept an uploaded letter can use Prof. Aliyev's generic one."
    )


def test_a_student_with_no_referees_yet_is_told_to_add_them() -> None:
    proposal = propose([_app("TUM", 2), _app("Lund", 1, "UPLOAD_GENERIC")], [])
    assert proposal.assignments == ()
    assert proposal.short == (
        "Your pack needs 3 letters. Add the professors who will write for you.",
    )


def test_an_unstated_count_proposes_nothing_and_is_listed() -> None:
    unknown = _app("Bologna", None)
    proposal = propose([unknown], [_ref(ALIYEV, "Prof. Aliyev")])
    assert proposal.assignments == () and proposal.unstated == (unknown.application_id,)
    assert proposal.short == ()


def test_kept_requests_fill_their_slot_and_use_up_the_referee() -> None:
    tum, kth = _app("TUM", 1), _app("KTH", 1)
    proposal = propose(
        [tum, kth],
        [_ref(ALIYEV, "Prof. Aliyev", agreed=1), _ref(KARIMOVA, "Prof. Karimova", agreed=1)],
        kept=[Assignment(tum.application_id, ALIYEV, "PORTAL_INVITE")],
    )
    assert proposal.assignments == (Assignment(kth.application_id, KARIMOVA, "PORTAL_INVITE"),)


@pytest.mark.parametrize("mode", ["", "NOT_STATED"])
def test_an_unstated_mode_counts_against_the_agreement(mode: str) -> None:
    proposal = propose([_app("TUM", 1, mode)], [_ref(ALIYEV, "Prof. Aliyev", agreed=0)])
    assert proposal.assignments == ()


def test_a_professor_who_declined_one_application_is_not_proposed_for_it_again() -> None:
    tum = _app("TUM", 1)
    proposal = propose(
        [tum], [_ref(ALIYEV, "Prof. Aliyev"), _ref(KARIMOVA, "Dr. Karimova", agreed=1)],
        declined=[(tum.application_id, ALIYEV)],
    )
    assert _who(proposal, tum) == {KARIMOVA}


def test_a_submitted_letter_fills_its_slot_after_its_professor_is_gone() -> None:
    card = _app("TUM", 1)
    proposal = propose(
        [card], [_ref(KARIMOVA, "Dr. Karimova")],
        kept=[Assignment(card.application_id, ALIYEV, "PORTAL_INVITE")],
    )
    assert proposal.assignments == () and proposal.short == ()


def test_a_single_letter_shortfall_does_not_say_different_referees() -> None:
    proposal = propose(
        [_app("Lund", 1, kind="ACADEMIC")], [_ref(HASANOV, "Mr. Hasanov", "PROFESSIONAL")]
    )
    assert proposal.short == ("Lund needs 1 academic letter. Add another academic referee.",)


def test_a_failed_repair_undoes_exactly_its_own_row() -> None:
    """O, P, N each need one letter; A and B agreed to one each; A declined P, B declined N.
    A failed deeper repair appends its evicted row, so undoing with pop() lost the wrong one."""
    a, b = uuid4(), uuid4()
    o, p, n = _app("O", 1, day=1), _app("P", 1, day=2), _app("N", 1, day=3)
    proposal = propose(
        [o, p, n], [_ref(a, "Prof. A", agreed=1), _ref(b, "Prof. B", agreed=1)],
        declined=[(p.application_id, a), (n.application_id, b)],
    )
    for who in (a, b):
        assert sum(1 for x in proposal.assignments if x.referee_id == who) <= 1
    assert len(proposal.assignments) == 2
    assert len({(x.application_id, x.referee_id) for x in proposal.assignments}) == 2
    assert not _who(proposal, p) & {a} and not _who(proposal, n) & {b}
    assert proposal.short  # O has nobody: reported, not silently dropped


def test_the_repair_never_proposes_a_declined_pair() -> None:
    tum, eth = _app("TUM", 1, kind="EITHER", day=1), _app("ETH", 1, kind="ACADEMIC", day=2)
    proposal = propose(
        [tum, eth],
        [_ref(ALIYEV, "Prof. Aliyev", agreed=1), _ref(HASANOV, "Mr. Hasanov", "PROFESSIONAL", 1)],
        declined=[(tum.application_id, HASANOV)],
    )
    assert _who(proposal, tum) == {ALIYEV} and _who(proposal, eth) == set()
    assert proposal.short


def test_the_repair_never_moves_a_kept_request() -> None:
    tum, eth = _app("TUM", 1, kind="EITHER", day=1), _app("ETH", 1, kind="ACADEMIC", day=2)
    proposal = propose(
        [tum, eth],
        [_ref(ALIYEV, "Prof. Aliyev", agreed=1), _ref(HASANOV, "Mr. Hasanov", "PROFESSIONAL", 1)],
        kept=[Assignment(tum.application_id, ALIYEV, "PORTAL_INVITE")],
    )
    assert proposal.assignments == () and proposal.short


def test_a_kept_generic_upload_from_a_non_giver_costs_a_request() -> None:
    lund, tum = _app("Lund", 1, "UPLOAD_GENERIC", day=1), _app("TUM", 1, day=2)
    proposal = propose(
        [lund, tum], [_ref(KARIMOVA, "Dr. Karimova", agreed=1)],
        kept=[Assignment(lund.application_id, KARIMOVA, "UPLOAD_GENERIC")],
    )
    assert proposal.assignments == ()


def test_an_assignment_that_needs_an_earlier_pick_moved_is_found() -> None:
    tum, eth = _app("TUM", 1, kind="EITHER"), _app("ETH", 1, kind="ACADEMIC")
    proposal = propose(
        [tum, eth],
        [_ref(ALIYEV, "Prof. Aliyev", agreed=1), _ref(HASANOV, "Mr. Hasanov", "PROFESSIONAL", 1)],
    )
    assert _who(proposal, tum) == {HASANOV} and _who(proposal, eth) == {ALIYEV}
    assert proposal.short == ()


def test_a_generic_upload_costs_a_request_unless_the_professor_gives_a_generic_letter() -> None:
    lund = _app("Lund", 1, "UPLOAD_GENERIC")
    assert propose([lund], [_ref(KARIMOVA, "Dr. Karimova", agreed=0)]).assignments == ()
    spends = propose([lund], [_ref(KARIMOVA, "Dr. Karimova", agreed=1)])
    assert _who(spends, lund) == {KARIMOVA}
    free = propose([lund], [_ref(KARIMOVA, "Dr. Karimova", agreed=0, generic=True)])
    assert _who(free, lund) == {KARIMOVA}


def test_grammar_of_the_too_few_sentences() -> None:
    one = propose([_app("TUM", 1)], [])
    assert one.short == ("Your pack needs 1 letter. Add the professors who will write for you.",)
    refs = [_ref(uuid4(), f"Prof. R{i}", agreed=0) for i in range(5)]
    many = propose([_app("TUM", 1)], refs)
    assert many.short[0].endswith("Ask another referee.")


def test_a_shortfall_of_one_kind_says_which_kind_to_add() -> None:
    proposal = propose(
        [_app("ETH", 2, kind="ACADEMIC")], [_ref(HASANOV, "Mr. Hasanov", "PROFESSIONAL", 1)]
    )
    assert proposal.short == (
        "Mr. Hasanov agreed to 1; your pack needs 2 portal letters. Ask a second academic referee.",
    )


def _optimum(needs: Sequence[ApplicationNeed], referees: Sequence[RefereeFacts]) -> int:
    """Brute force: the most slots fillable, each referee within agreed requests."""
    from itertools import product

    slots = [(n, k) for n in needs for k in range(n.letters or 0)]
    best = 0
    for pick in product([None, *referees], repeat=len(slots)):
        used: dict[UUID, int] = {}
        on: set[tuple[UUID, UUID]] = set()
        filled = 0
        for (n, _k), r in zip(slots, pick, strict=True):
            if r is None:
                continue
            if (n.application_id, r.referee_id) in on or not (
                n.kind in ("", "EITHER") or r.kind == n.kind
            ):
                break
            generic_free = n.mode == "UPLOAD_GENERIC" and r.gives_generic_letter
            cost = int(not generic_free)
            if used.get(r.referee_id, 0) + cost > r.agreed_requests:
                break
            used[r.referee_id] = used.get(r.referee_id, 0) + cost
            on.add((n.application_id, r.referee_id))
            filled += 1
        else:
            best = max(best, filled)
    return best


def _check_invariants(
    needs: Sequence[ApplicationNeed],
    referees: Sequence[RefereeFacts],
    proposal: Proposal,
    kept: Sequence[Assignment] = (),
    declined: Sequence[tuple[UUID, UUID]] = (),
) -> None:
    by_ref = {r.referee_id: r for r in referees}
    by_app = {n.application_id: n for n in needs}
    pairs = [(x.application_id, x.referee_id) for x in (*kept, *proposal.assignments)]
    assert len(pairs) == len(set(pairs))
    assert not {(x.application_id, x.referee_id) for x in proposal.assignments} & set(declined)
    for ref in referees:
        mine = [x for x in proposal.assignments if x.referee_id == ref.referee_id]
        if mine:
            total = sum(
                _cost_of(by_app[x.application_id], ref)
                for x in (*kept, *proposal.assignments)
                if x.referee_id == ref.referee_id
            )
            assert total <= ref.agreed_requests
    assert all(x.referee_id in by_ref for x in proposal.assignments)


def _cost_of(need: ApplicationNeed, ref: RefereeFacts) -> int:
    generic_free = need.mode == "UPLOAD_GENERIC" and ref.gives_generic_letter
    return int(not generic_free)


def _random_case(rng: random.Random) -> tuple[list[ApplicationNeed], list[RefereeFacts]]:
    needs = [
        _app(f"P{i}", rng.randint(1, 2), rng.choice(["PORTAL_INVITE", "UPLOAD_GENERIC"]),
             kind=rng.choice(["", "ACADEMIC", "PROFESSIONAL", "EITHER"]))
        for i in range(rng.randint(1, 4))
    ]
    referees = [
        _ref(uuid4(), f"R{i}", rng.choice(["ACADEMIC", "PROFESSIONAL"]), rng.randint(0, 3),
             rng.random() < 0.4)
        for i in range(rng.randint(1, 3))
    ]
    return needs, referees


def test_the_proposer_fills_as_many_slots_as_a_brute_force_optimum() -> None:
    rng = random.Random(20261013)
    for _ in range(300):
        needs, referees = _random_case(rng)
        proposal = propose(needs, referees)
        assert len(proposal.assignments) == _optimum(needs, referees), (needs, referees)
        _check_invariants(needs, referees, proposal)


def test_declined_and_kept_requests_are_respected_on_random_cases() -> None:
    rng = random.Random(7)
    for _ in range(1500):
        needs, referees = _random_case(rng)
        declined = [
            (n.application_id, r.referee_id)
            for n in needs for r in referees if rng.random() < 0.25
        ]
        kept: list[Assignment] = []
        spent: dict[UUID, int] = {}
        for n in needs:
            for r in referees:
                if (n.application_id, r.referee_id) in declined or rng.random() > 0.2:
                    continue
                cost = _cost_of(n, r)
                if spent.get(r.referee_id, 0) + cost <= r.agreed_requests:
                    spent[r.referee_id] = spent.get(r.referee_id, 0) + cost
                    kept.append(Assignment(n.application_id, r.referee_id, n.mode))
        proposal = propose(needs, referees, kept=kept, declined=declined)
        _check_invariants(needs, referees, proposal, kept, declined)


_MODES = ("PORTAL_INVITE", "REFEREE_SENDS", "UPLOAD_GENERIC", "UPLOAD_ADDRESSED", "")


def _cost(need: ApplicationNeed, ref: RefereeFacts) -> int:
    from apps.documents.referee_plan import costs_a_request

    if costs_a_request(need.mode):
        return 1
    return int(need.mode == "UPLOAD_GENERIC" and not ref.gives_generic_letter)


def _large_case(
    rng: random.Random,
) -> tuple[list[ApplicationNeed], list[RefereeFacts], list[Assignment], list[tuple[UUID, UUID]]]:
    """Up to 8 applications x 6 referees, with kept and declined rows (final review D1)."""
    needs = [
        ApplicationNeed(
            uuid4(), f"P{i}", rng.choice([None, 1, 2, 3]),
            rng.choice(["", "EITHER", "ACADEMIC", "PROFESSIONAL"]), rng.choice(_MODES),
            rng.random() < 0.3,
            rng.choice([None, datetime(2027, 1, rng.randint(1, 28), tzinfo=UTC)]),
            rng.random() < 0.3,
        )
        for i in range(rng.randint(1, 8))
    ]
    referees = [
        _ref(uuid4(), f"R{i}", rng.choice(["ACADEMIC", "PROFESSIONAL"]), rng.randint(0, 4),
             rng.random() < 0.4, rng.random() < 0.5)
        for i in range(rng.randint(1, 6))
    ]
    kept: list[Assignment] = []
    declined: list[tuple[UUID, UUID]] = []
    spent: dict[UUID, int] = {}
    for n in needs:
        for r in referees:
            roll = rng.random()
            if roll < 0.12:
                # Mostly within the agreement; now and then over it (asked by hand).
                cost = _cost(n, r)
                if spent.get(r.referee_id, 0) + cost <= r.agreed_requests or rng.random() < 0.1:
                    spent[r.referee_id] = spent.get(r.referee_id, 0) + cost
                    kept.append(Assignment(n.application_id, r.referee_id, n.mode or "NOT_STATED"))
            elif roll < 0.3:
                declined.append((n.application_id, r.referee_id))
    return needs, referees, kept, declined


def _max_new_letters(
    needs: Sequence[ApplicationNeed],
    referees: Sequence[RefereeFacts],
    kept: Sequence[Assignment],
    declined: Sequence[tuple[UUID, UUID]],
) -> int:
    """The most new letters any plan could add: a max flow from each application's
    open slots to its capable referees, a paid edge per referee for what is left of their
    agreement and a free one (a generic letter from a giver, an addressed upload) while
    they are not over it. The proposer refuses a free one too once a referee is over."""
    from collections import deque

    by_ref = {r.referee_id: r for r in referees}
    used = {r.referee_id: 0 for r in referees}
    on: dict[UUID, set[UUID]] = {n.application_id: set() for n in needs}
    for k in kept:
        need = next(n for n in needs if n.application_id == k.application_id)
        used[k.referee_id] += _cost(need, by_ref[k.referee_id])
        on[k.application_id].add(k.referee_id)
    cap: dict[tuple[object, object], int] = {}

    def edge(u: object, v: object, c: int) -> None:
        cap[u, v] = cap.get((u, v), 0) + c
        cap.setdefault((v, u), 0)

    for r in referees:
        edge(("paid", r.referee_id), "T", max(0, r.agreed_requests - used[r.referee_id]))
        edge(("free", r.referee_id), "T", 99 if used[r.referee_id] <= r.agreed_requests else 0)
    for need in needs:
        if need.letters is None:
            continue
        edge("S", need.application_id, max(0, need.letters - len(on[need.application_id])))
        for r in referees:
            if (
                (need.kind in ("", "EITHER") or r.kind == need.kind)
                and r.referee_id not in on[need.application_id]
                and (need.application_id, r.referee_id) not in declined
            ):
                sink = "paid" if _cost(need, r) else "free"
                edge(need.application_id, (sink, r.referee_id), 1)
    nexts: dict[object, list[object]] = {}
    for u, v in cap:
        nexts.setdefault(u, []).append(v)
    flow = 0
    while True:
        back: dict[object, object | None] = {"S": None}
        queue: deque[object] = deque(["S"])
        while queue and "T" not in back:
            u = queue.popleft()
            for v in nexts.get(u, ()):
                if v not in back and cap[u, v] > 0:
                    back[v] = u
                    queue.append(v)
        if "T" not in back:
            return flow
        v = "T"
        while back[v] is not None:
            prev = back[v]
            assert prev is not None
            cap[prev, v] -= 1
            cap[v, prev] += 1
            v = prev
        flow += 1


def test_large_random_plans_keep_every_invariant() -> None:
    """Capacity, distinct pairs, declined and kept pairs respected, kind fit, no over-fill,
    nothing left that one more pick could fill, "short" said exactly when short, and as
    many new letters as any plan could add (final review D1: this is what catches a
    repair step that leaves a slot empty without breaking any other rule)."""
    rng = random.Random(20261014)
    for _ in range(3000):
        needs, referees, kept, declined = _large_case(rng)
        proposal = propose(needs, referees, kept=kept, declined=declined)
        case = (needs, referees, kept, declined, proposal)
        by_ref = {r.referee_id: r for r in referees}
        new = [(a.application_id, a.referee_id) for a in proposal.assignments]
        old = [(k.application_id, k.referee_id) for k in kept]
        assert len(new) == len(set(new)), case
        assert not set(new) & set(old), case
        assert not set(new) & set(declined), case
        used = {r.referee_id: 0 for r in referees}
        on: dict[UUID, set[UUID]] = {n.application_id: set() for n in needs}
        for need in needs:
            for app_id, ref_id in (*old, *new):
                if app_id == need.application_id:
                    used[ref_id] += _cost(need, by_ref[ref_id])
                    on[app_id].add(ref_id)
        for a in proposal.assignments:
            need = next(n for n in needs if n.application_id == a.application_id)
            ref = by_ref[a.referee_id]
            assert need.kind in ("", "EITHER") or ref.kind == need.kind, case
            assert used[ref.referee_id] <= ref.agreed_requests, case
            assert need.letters is not None and len(on[need.application_id]) <= need.letters, case
        short = False
        for need in needs:
            if need.letters is None or len(on[need.application_id]) >= need.letters:
                continue
            short = True
            for ref in referees:
                assert not (
                    (need.kind in ("", "EITHER") or ref.kind == need.kind)
                    and ref.referee_id not in on[need.application_id]
                    and (need.application_id, ref.referee_id) not in declined
                    and used[ref.referee_id] + _cost(need, ref) <= ref.agreed_requests
                ), ("a free slot left unfilled", case)
        assert short == bool(proposal.short), case
        assert len(new) == _max_new_letters(needs, referees, kept, declined), case


def test_role_complementarity_pairs_research_supervisor_with_course_instructor() -> None:
    eth = _app("ETH", 2, kind="ACADEMIC")
    r_course1 = RefereeFacts(
        ALIYEV, "Prof. Course1", "ACADEMIC", 5, role_archetype="course_instructor"
    )
    r_course2 = RefereeFacts(
        KARIMOVA, "Prof. Course2", "ACADEMIC", 4, role_archetype="course_instructor"
    )
    r_thesis = RefereeFacts(
        HASANOV, "Prof. Thesis", "ACADEMIC", 3, role_archetype="research_supervisor"
    )
    proposal = propose([eth], [r_course1, r_course2, r_thesis])
    assert _who(proposal, eth) == {ALIYEV, HASANOV}


def test_evidence_backed_research_supervisor_beats_high_quota_course_instructor() -> None:
    oxford = _app("Oxford", 1, kind="ACADEMIC")
    r_course = RefereeFacts(
        ALIYEV, "Prof. Course", "ACADEMIC", 6,
        role_archetype="course_instructor", shared_work_score=0,
    )
    r_thesis = RefereeFacts(
        HASANOV, "Prof. Thesis", "ACADEMIC", 3,
        role_archetype="research_supervisor", shared_work_score=2,
    )
    proposal = propose([oxford], [r_course, r_thesis])
    assert _who(proposal, oxford) == {HASANOV}


def test_non_strict_programme_does_not_waste_scarce_institutional_email_referee() -> None:
    p0_no_email = _app("P0", 1, kind="EITHER", day=1, funding=True, email=False)
    p1_strict_email = _app("P1", 1, kind="EITHER", day=2, funding=True, email=True)
    r_inst = _ref(ALIYEV, "Dr. A_Inst", "ACADEMIC", agreed=1, institutional=True)
    r_gmail = _ref(KARIMOVA, "Dr. B_Gmail", "ACADEMIC", agreed=1, institutional=False)
    proposal = propose([p0_no_email, p1_strict_email], [r_inst, r_gmail])
    assert _who(proposal, p1_strict_email) == {ALIYEV}
    assert _who(proposal, p0_no_email) == {KARIMOVA}
    assert not any(a.email_flag for a in proposal.assignments)


def test_convex_load_balancing_spreads_requests_across_equal_referees() -> None:
    app1, app2 = _app("App1", 1), _app("App2", 1)
    r_alpha = _ref(ALIYEV, "Prof. Alpha", "ACADEMIC", agreed=3)
    r_beta = _ref(KARIMOVA, "Prof. Beta", "ACADEMIC", agreed=3)
    proposal = propose([app1, app2], [r_alpha, r_beta])
    assert {a.referee_id for a in proposal.assignments} == {ALIYEV, KARIMOVA}


def test_composite_min_academic_quota_enforced_on_mixed_programme() -> None:
    imperial = ApplicationNeed(
        application_id=uuid4(), title="Imperial", letters=2, kind="EITHER",
        mode="PORTAL_INVITE", min_academic=1,
    )
    r_mgr1 = RefereeFacts(ALIYEV, "Mgr. One", "PROFESSIONAL", 5, shared_work_score=5)
    r_mgr2 = RefereeFacts(KARIMOVA, "Mgr. Two", "PROFESSIONAL", 5, shared_work_score=5)
    r_acad = RefereeFacts(HASANOV, "Prof. Acad", "ACADEMIC", 1, shared_work_score=0)
    proposal = propose([imperial], [r_mgr1, r_mgr2, r_acad])
    assert HASANOV in _who(proposal, imperial) and len(_who(proposal, imperial)) == 2


def test_upload_addressed_costs_a_request_and_webmail_blocked_defaults_false() -> None:
    from types import SimpleNamespace

    from apps.documents.referee_plan import costs_a_request
    from apps.documents.referee_views import _webmail_blocked_for

    assert costs_a_request("UPLOAD_GENERIC") is False
    assert costs_a_request("UPLOAD_ADDRESSED") is True

    # UPLOAD_ADDRESSED requires an agreed request even when gives_generic_letter=True
    addressed = _app("ETH", 1, "UPLOAD_ADDRESSED")
    zero_agreed = _ref(ALIYEV, "Prof. Aliyev", agreed=0, generic=True)
    assert propose([addressed], [zero_agreed]).assignments == ()
    one_agreed = _ref(ALIYEV, "Prof. Aliyev", agreed=1, generic=True)
    assert _who(propose([addressed], [one_agreed]), addressed) == {ALIYEV}

    # Negative agreed_requests and shared_work_score clamp safely to 0
    neg_ref = RefereeFacts(
        ALIYEV, "Prof. Neg", "ACADEMIC", agreed_requests=-2, shared_work_score=-5
    )
    assert propose([_app("TUM", 1)], [neg_ref]).assignments == ()

    # _webmail_blocked_for defaults to False when only institutional_email=True
    soft_need = SimpleNamespace(institutional_email=True)
    assert _webmail_blocked_for(soft_need) is False
    hard_need = SimpleNamespace(institutional_email=True, webmail_blocked=True)
    assert _webmail_blocked_for(hard_need) is True

    # UPLOAD_GENERIC with only gives_generic_letter=False referees reports quota shortfall
    upload_gen = _app("Aalto", 2, "UPLOAD_GENERIC")
    non_gen_1 = _ref(ALIYEV, "Prof. Aliyev", agreed=1, generic=False)
    non_gen_2 = _ref(KARIMOVA, "Prof. Karimova", agreed=0, generic=False)
    prop_short = propose([upload_gen], [non_gen_1, non_gen_2])
    assert any("agreed to 1" in line for line in prop_short.short)



