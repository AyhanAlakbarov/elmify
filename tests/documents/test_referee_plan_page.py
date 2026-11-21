"""The referee plan page (lanes spec §11.2): propose, edit, swap."""

import pytest

from apps.documents.models import Referee, RefereeRequest
from apps.funding.models import RecommendationCandidate
from apps.tenancy.context import tenant_scope
from tests.conftest import reads_no_catalogue
from tests.dashboard import conftest as dashboard_conftest
from tests.dashboard.conftest import add_card

pytestmark = pytest.mark.django_db
pack = dashboard_conftest.pack  # the fixture, shared with the dashboard tests
PAGE = "/student/referees/plan/"
PROPOSE = "/student/referees/plan/propose/"


def _records(*pairs, text="Two academic letters, invited through the portal."):
    return [
        {"field": f, "value": v, "date": "", "conditional": False, "condition": "",
         "rule_text": text, "source_url": "https://campus.tum.de/apply"}
        for f, v in pairs
    ]


def _referee(agency, student, name, **extra):
    fields = {"title": "Prof.", "agreed_requests": 3, "institutional_email": True, **extra}
    return Referee.objects.create(tenant=agency, student=student, name=name, **fields)


@pytest.fixture
def card(agency_a, membership_a, pack):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(
            referee_requirements=_records(("count", "TWO"), ("mode", "PORTAL_INVITE"))
        )
        programme.refresh_from_db()
        return add_card(agency_a, membership_a, programme)


def _states(agency, student):
    with tenant_scope(agency.id):
        return sorted(
            (q.referee.name, q.state, q.mode)
            for q in RefereeRequest.objects.filter(referee__student=student)
            .select_related("referee")
        )


def test_propose_writes_proposed_requests_that_meet_the_count(
    client, agency_a, domain_a, user_a, membership_a, card
) -> None:
    with tenant_scope(agency_a.id):
        _referee(agency_a, membership_a, "Aliyev")
        _referee(agency_a, membership_a, "Karimova")
    client.force_login(user_a)
    client.post(PROPOSE, HTTP_HOST=domain_a.host)
    assert _states(agency_a, membership_a) == [
        ("Aliyev", "PROPOSED", "PORTAL_INVITE"), ("Karimova", "PROPOSED", "PORTAL_INVITE"),
    ]
    with reads_no_catalogue():
        body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "M.Sc. Informatics" in body
    assert "Prof. Aliyev — proposed" in body and "Prof. Karimova — proposed" in body
    assert "Two academic letters, invited through the portal." in body
    # kind, institutional address and due were not stated on the page.
    assert body.count("Not stated — check the page") == 3


def test_too_few_says_so_in_the_spec_s_shape(
    client, agency_a, domain_a, user_a, membership_a, card
) -> None:
    with tenant_scope(agency_a.id):
        _referee(agency_a, membership_a, "Aliyev", agreed_requests=1)
    client.force_login(user_a)
    client.post(PROPOSE, HTTP_HOST=domain_a.host)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert (
        "Prof. Aliyev agreed to 1; your pack needs 2 portal letters. Ask a second referee."
    ) in body


def test_a_page_that_states_no_count_proposes_nothing(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
        _referee(agency_a, membership_a, "Aliyev")
    client.force_login(user_a)
    client.post(PROPOSE, HTTP_HOST=domain_a.host)
    assert _states(agency_a, membership_a) == []
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert body.count("Not stated — check the page") == 5


def test_swap_declines_open_requests_and_proposes_again(
    client, agency_a, domain_a, user_a, membership_a, card
) -> None:
    with tenant_scope(agency_a.id):
        aliyev = _referee(agency_a, membership_a, "Aliyev")
        karimova = _referee(agency_a, membership_a, "Karimova")
        _referee(agency_a, membership_a, "Hasanov", agreed_requests=1)
        RefereeRequest.objects.create(
            tenant=agency_a, referee=aliyev, application=card, mode="PORTAL_INVITE",
            state="ASKED",
        )
        RefereeRequest.objects.create(
            tenant=agency_a, referee=karimova, application=card, mode="PORTAL_INVITE",
        )
    client.force_login(user_a)
    client.post(
        f"/student/referees/{aliyev.id}/status/", {"status": "SILENT"}, HTTP_HOST=domain_a.host
    )
    assert _states(agency_a, membership_a) == [
        ("Aliyev", "DECLINED", "PORTAL_INVITE"),
        ("Hasanov", "PROPOSED", "PORTAL_INVITE"),
        ("Karimova", "PROPOSED", "PORTAL_INVITE"),
    ]


def test_the_student_edits_the_proposal(
    client, agency_a, domain_a, user_a, membership_a, card
) -> None:
    with tenant_scope(agency_a.id):
        aliyev = _referee(agency_a, membership_a, "Aliyev")
        asked = RefereeRequest.objects.create(
            tenant=agency_a, referee=_referee(agency_a, membership_a, "Karimova"),
            application=card, state="ASKED",
        )
    client.force_login(user_a)
    client.post(
        "/student/referees/plan/add/",
        {"referee_id": str(aliyev.id), "application_id": str(card.id)},
        HTTP_HOST=domain_a.host,
    )
    with tenant_scope(agency_a.id):
        added = RefereeRequest.objects.get(referee=aliyev)
    assert (added.state, added.mode) == ("PROPOSED", "PORTAL_INVITE")
    client.post(f"/student/referees/requests/{added.id}/remove/", HTTP_HOST=domain_a.host)
    refused = client.post(
        f"/student/referees/requests/{asked.id}/remove/", HTTP_HOST=domain_a.host
    )
    assert refused.status_code == 404
    # Removed is marked, not deleted: never proposed again until the student adds it back.
    assert _states(agency_a, membership_a) == [
        ("Aliyev", "DECLINED", "PORTAL_INVITE"), ("Karimova", "ASKED", "NOT_STATED"),
    ]


def test_a_silent_professor_who_answers_can_be_put_back(
    client, agency_a, domain_a, user_a, membership_a, card
) -> None:
    with tenant_scope(agency_a.id):
        aliyev = _referee(agency_a, membership_a, "Aliyev")
        RefereeRequest.objects.create(
            tenant=agency_a, referee=aliyev, application=card, mode="PORTAL_INVITE",
            state="ASKED",
        )
    client.force_login(user_a)
    for status in ("SILENT", "ACTIVE"):
        client.post(
            f"/student/referees/{aliyev.id}/status/", {"status": status},
            HTTP_HOST=domain_a.host,
        )
    assert _states(agency_a, membership_a) == [("Aliyev", "DECLINED", "PORTAL_INVITE")]
    client.post(
        "/student/referees/plan/add/",
        {"referee_id": str(aliyev.id), "application_id": str(card.id)},
        HTTP_HOST=domain_a.host,
    )
    assert _states(agency_a, membership_a) == [("Aliyev", "PROPOSED", "PORTAL_INVITE")]


def test_a_decided_application_gets_no_new_referee(
    client, agency_a, domain_a, user_a, membership_a, card
) -> None:
    with tenant_scope(agency_a.id):
        _referee(agency_a, membership_a, "Aliyev")
        card.outcome = "REJECTED"
        card.save(update_fields=["outcome"])
    client.force_login(user_a)
    client.post(PROPOSE, HTTP_HOST=domain_a.host)
    assert _states(agency_a, membership_a) == []


def test_propose_twice_keeps_one_plan_and_takes_the_student_lock(
    client, agency_a, domain_a, user_a, membership_a, card
) -> None:
    """Two tabs: the second proposal waits on the student's row instead of racing the
    first into the unique pair (the lock is asserted because a test cannot race)."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.documents.referee_views import repropose

    with tenant_scope(agency_a.id):
        _referee(agency_a, membership_a, "Aliyev")
        _referee(agency_a, membership_a, "Karimova")
    client.force_login(user_a)
    client.post(PROPOSE, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id), CaptureQueriesContext(connection) as queries:
        repropose(membership_a)
    assert any(
        "FOR UPDATE" in q["sql"] and "tenancy_membership" in q["sql"]
        for q in queries.captured_queries
    )
    assert [state for _name, state, _mode in _states(agency_a, membership_a)] == [
        "PROPOSED", "PROPOSED",
    ]


def test_another_students_referee_or_application_is_404(
    client, agency_a, domain_a, user_a, user_b, membership_a, card
) -> None:
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        theirs = _referee(agency_a, other, "Mammadov")
    client.force_login(user_a)
    response = client.post(
        "/student/referees/plan/add/",
        {"referee_id": str(theirs.id), "application_id": str(card.id)},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 404


def test_a_submitted_letter_still_fills_its_slot_when_its_professor_goes_silent(
    client, agency_a, domain_a, user_a, membership_a, card
) -> None:
    with tenant_scope(agency_a.id):
        aliyev = _referee(agency_a, membership_a, "Aliyev")
        _referee(agency_a, membership_a, "Karimova")
        _referee(agency_a, membership_a, "Hasanov")
        RefereeRequest.objects.create(
            tenant=agency_a, referee=aliyev, application=card, mode="PORTAL_INVITE",
            state="SUBMITTED",
        )
    client.force_login(user_a)
    client.post(
        f"/student/referees/{aliyev.id}/status/", {"status": "SILENT"}, HTTP_HOST=domain_a.host
    )
    states = _states(agency_a, membership_a)
    assert ("Aliyev", "SUBMITTED", "PORTAL_INVITE") in states and len(states) == 2


def test_propose_respects_capacity_with_declined_rows(
    client, agency_a, domain_a, user_a, membership_a, pack, program_factory
) -> None:
    """Three cards, two professors who agreed to one each, two declined pairs: the plan
    the endpoint writes keeps every professor within their agreement (the repair's undo)."""
    from tests.funding.conftest import make_db_candidate, make_run

    programme, _award = pack
    run = make_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        candidates = [programme] + [
            make_db_candidate(agency_a, run, program_name=f"Programme {i}") for i in range(2)
        ]
        for i, candidate in enumerate(candidates):
            RecommendationCandidate.objects.filter(id=candidate.id).update(
                program_id=candidate.program_id or program_factory(name=f"Prog {i}").id,
                referee_requirements=_records(("count", "ONE"), ("mode", "PORTAL_INVITE"))
            )
            candidate.refresh_from_db()
        cards = [add_card(agency_a, membership_a, c) for c in candidates]
        a = _referee(agency_a, membership_a, "Aliyev", agreed_requests=1)
        b = _referee(agency_a, membership_a, "Karimova", agreed_requests=1)
        for application, referee in ((cards[1], a), (cards[2], b)):
            RefereeRequest.objects.create(
                tenant=agency_a, referee=referee, application=application,
                mode="PORTAL_INVITE", state="DECLINED",
            )
    client.force_login(user_a)
    client.post(PROPOSE, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        proposed = list(RefereeRequest.objects.filter(state="PROPOSED"))
    assert len(proposed) == 2
    assert len({q.referee_id for q in proposed}) == 2
    assert not {(q.application_id, q.referee_id) for q in proposed} & {
        (cards[1].id, a.id), (cards[2].id, b.id)
    }


def _cards(agency, student, pack, program_factory, *specs):
    """One card per (name, letters, mode, day): the candidate's referee facts and a
    route deadline on its own snapshot."""
    from tests.funding.conftest import make_db_candidate

    programme, _award = pack
    cards = {}
    for name, letters, mode, day in specs:
        candidate = make_db_candidate(agency, programme.run, program_name=name)
        with tenant_scope(agency.id):
            RecommendationCandidate.objects.filter(id=candidate.id).update(
                program_id=program_factory(name=name).id,
                referee_requirements=_records(("count", letters), ("mode", mode)),
            )
            candidate.refresh_from_db()
            cards[name] = add_card(agency, student, candidate, route_snapshot={
                "source": "CATALOGUE", "steps": [{
                    "position": 1, "purpose": "APPLY", "channel": "PORTAL",
                    "dates": [{"role": "FINAL", "date": day, "timezone": "Europe/Berlin"}],
                }],
            })
    return cards


def _on(agency, application):
    with tenant_scope(agency.id):
        return sorted(
            (q.referee.name, q.state)
            for q in RefereeRequest.objects.filter(application=application)
            .select_related("referee")
        )


def test_a_removed_professor_stays_off_after_another_professor_is_swapped(
    client, agency_a, domain_a, user_a, membership_a, pack, program_factory
) -> None:
    """Final review I3: the student's edit is not undone by the next swap."""
    cards = _cards(agency_a, membership_a, pack, program_factory,
                   ("Rostock Informatics", "ONE", "PORTAL_INVITE", "2027-01-10"),
                   ("Riga Physics", "ONE", "PORTAL_INVITE", "2027-02-10"))
    rostock, riga = cards["Rostock Informatics"], cards["Riga Physics"]
    with tenant_scope(agency_a.id):
        aliyev = _referee(agency_a, membership_a, "Aliyev", agreed_requests=2)
        karimova = _referee(agency_a, membership_a, "Karimova", agreed_requests=2)
    client.force_login(user_a)
    client.post(PROPOSE, HTTP_HOST=domain_a.host)
    assert _on(agency_a, rostock) == [("Aliyev", "PROPOSED")]
    with tenant_scope(agency_a.id):
        r1 = RefereeRequest.objects.get(application=rostock)
    client.post(f"/student/referees/requests/{r1.id}/remove/", HTTP_HOST=domain_a.host)
    client.post(
        f"/student/referees/{karimova.id}/status/", {"status": "SILENT"},
        HTTP_HOST=domain_a.host,
    )
    assert _on(agency_a, rostock) == [("Aliyev", "DECLINED")]
    assert _on(agency_a, riga) == [("Aliyev", "PROPOSED")]
    package = client.get(
        f"/student/referees/{aliyev.id}/package/", HTTP_HOST=domain_a.host
    ).content.decode()
    assert "Riga Physics" in package and "Rostock Informatics" not in package


def test_a_hand_added_professor_survives_a_swap_and_the_propose_button_resets(
    client, agency_a, domain_a, user_a, membership_a, pack, program_factory
) -> None:
    rostock = _cards(agency_a, membership_a, pack, program_factory,
                     ("Rostock Informatics", "ONE", "PORTAL_INVITE", "2027-01-10"))[
                         "Rostock Informatics"]
    with tenant_scope(agency_a.id):
        _referee(agency_a, membership_a, "Aliyev")
        karimova = _referee(agency_a, membership_a, "Karimova")
        hasanov = _referee(agency_a, membership_a, "Hasanov")
    client.force_login(user_a)
    client.post(PROPOSE, HTTP_HOST=domain_a.host)
    assert _on(agency_a, rostock) == [("Aliyev", "PROPOSED")]
    client.post(
        "/student/referees/plan/add/",
        {"referee_id": str(karimova.id), "application_id": str(rostock.id)},
        HTTP_HOST=domain_a.host,
    )
    client.post(
        f"/student/referees/{hasanov.id}/status/", {"status": "DECLINED"},
        HTTP_HOST=domain_a.host,
    )
    assert _on(agency_a, rostock) == [("Aliyev", "PROPOSED"), ("Karimova", "PROPOSED")]
    client.post(PROPOSE, HTTP_HOST=domain_a.host)
    assert _on(agency_a, rostock) == [("Aliyev", "PROPOSED")]


def test_a_programme_an_award_card_links_to_gets_the_strongest_referee_first(
    client, agency_a, domain_a, user_a, membership_a, pack, program_factory
) -> None:
    """Final review I4: the award's own card states no letters, so "funding-deciding"
    must mark the programme card the award links to (spec §11.2)."""
    from apps.documents.referee_views import application_needs
    from apps.portals.models import ApplicationLink

    _programme, award = pack
    cards = _cards(agency_a, membership_a, pack, program_factory,
                   ("Early Programme", "ONE", "PORTAL_INVITE", "2027-01-10"),
                   ("Funded Programme", "ONE", "PORTAL_INVITE", "2027-03-10"))
    early, funded = cards["Early Programme"], cards["Funded Programme"]
    with tenant_scope(agency_a.id):
        award_card = add_card(agency_a, membership_a, award, portal=False)
        ApplicationLink.objects.create(tenant=agency_a, from_app=award_card, to_app=funded)
        _referee(agency_a, membership_a, "Aliyev", agreed_requests=1)
        _referee(agency_a, membership_a, "Bakirov", agreed_requests=1, kind="PROFESSIONAL")
        with reads_no_catalogue():
            deciding = {
                application.id: n.funding_deciding
                for application, _need, n in application_needs(
                    membership_a, [early, funded, award_card]
                )
            }
    assert deciding == {early.id: False, funded.id: True, award_card.id: False}
    client.force_login(user_a)
    client.post(PROPOSE, HTTP_HOST=domain_a.host)
    assert _on(agency_a, funded) == [("Aliyev", "PROPOSED")]
    assert _on(agency_a, early) == [("Bakirov", "PROPOSED")]


def test_a_proposal_left_on_a_decided_card_uses_up_nobody(
    client, agency_a, domain_a, user_a, membership_a, pack, program_factory
) -> None:
    """Final review M2: a PROPOSED request on a card since decided is not a request
    anyone will make, so the plan page's "too few" check does not count it."""
    cards = _cards(agency_a, membership_a, pack, program_factory,
                   ("Open Programme", "ONE", "PORTAL_INVITE", "2027-01-10"),
                   ("Refused Programme", "ONE", "PORTAL_INVITE", "2027-02-10"))
    with tenant_scope(agency_a.id):
        aliyev = _referee(agency_a, membership_a, "Aliyev", agreed_requests=1)
        refused = cards["Refused Programme"]
        RefereeRequest.objects.create(
            tenant=agency_a, referee=aliyev, application=refused, mode="PORTAL_INVITE",
        )
        refused.outcome = "REJECTED"
        refused.save(update_fields=["outcome"])
    client.force_login(user_a)
    with reads_no_catalogue():
        body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert 'role="alert"' not in body
