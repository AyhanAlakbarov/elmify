from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from apps.funding.models import FundingOpportunity, RecommendationCandidate
from apps.portals import applications as applications_module
from apps.portals.applications import add_application
from apps.portals.models import Application, ApplicationLink
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.funding.conftest import make_db_candidate, make_published_pack, make_run

pytestmark = pytest.mark.django_db

SEP = "STUDENT_APPLIES_SEPARATELY"


@pytest.fixture(autouse=True)
def _no_queue(monkeypatch):
    monkeypatch.setattr(applications_module, "enqueue_document_work", lambda *_a, **_k: None)


def _award(agency, run, name, route, *, eligible=True, confidence="MEDIUM", state="VISIBLE"):
    opportunity = FundingOpportunity.objects.create(
        canonical_key=f"award:{uuid4()}", name=name, family="UNIVERSITY_WIDE", scope_type="GLOBAL",
    )
    award = make_db_candidate(
        agency, run, program_name=name, eligible=eligible,
        evidence_confidence=confidence, state=state,
    )
    with tenant_scope(agency.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            funding_card={"scope": "GLOBAL", "route": route}, opportunity_id=opportunity.id,
        )
    award.refresh_from_db()
    return award


def _pack(agency, membership, *, awards):
    run = make_run(agency, membership)
    programme = make_db_candidate(agency, run, program_name="MSc Chemistry")
    made = [_award(agency, run, *spec[:2], **spec[2]) for spec in awards]
    make_published_pack(agency, run, (programme, *made))
    return programme, made


def test_a_separate_eligible_award_is_added_and_linked(agency_a, membership_a) -> None:
    programme, (award,) = _pack(agency_a, membership_a, awards=[("SI Scholarship", SEP, {})])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        award_card = Application.objects.get(candidate=award)
        link = ApplicationLink.objects.get()
    assert (link.from_app_id, link.to_app_id, link.order) == (award_card.id, card.id, "LINKED_ONLY")


def test_only_confirmed_eligible_separate_awards_become_cards(agency_a, membership_a) -> None:
    programme, _awards = _pack(agency_a, membership_a, awards=[
        ("Automatic waiver", "AUTOMATIC_ON_ADMISSION", {}),
        ("Considered", "CONSIDERED_WITH_ADMISSION", {}),
        ("Nominated", "INSTITUTION_NOMINATES", {}),
        ("Joint", "JOINT_SELECTION", {}),
        ("Unstated", "UNSTATED", {}),
        ("Low confidence", SEP, {"confidence": "LOW"}),
        ("Not eligible", SEP, {"eligible": False}),
        ("Rejected", SEP, {"state": "REJECTED"}),
        ("Home government", "HOME_GOVERNMENT_NOMINATES", {}),
    ])
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        names = sorted(
            Application.objects.exclude(candidate=programme)
            .values_list("candidate__program_name", flat=True)
        )
    assert names == ["Home government"]


def test_adding_twice_adds_awards_once(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[("SI Scholarship", SEP, {})])
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        assert Application.objects.count() == 2
        assert ApplicationLink.objects.count() == 1


def test_one_award_for_two_programmes_is_one_card_linked_twice(agency_a, membership_a) -> None:
    run = make_run(agency_a, membership_a)
    first = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    second = make_db_candidate(agency_a, run, program_name="MSc Physics")
    award = _award(agency_a, run, "Chevening", SEP)
    make_published_pack(agency_a, run, (first, second, award))
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=first.id, actor=membership_a)
        add_application(student=membership_a, candidate_id=second.id, actor=membership_a)
        assert Application.objects.filter(candidate=award).count() == 1
        funded = ApplicationLink.objects.values_list("to_app__candidate__program_name", flat=True)
        assert sorted(funded) == ["MSc Chemistry", "MSc Physics"]


def test_an_award_added_directly_links_to_programmes_on_the_board(agency_a, membership_a) -> None:
    programme, (award,) = _pack(agency_a, membership_a, awards=[("SI Scholarship", SEP, {})])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        ApplicationLink.objects.all().delete()
        Application.objects.filter(candidate=award).delete()
        award_card = add_application(
            student=membership_a, candidate_id=award.id, actor=membership_a
        )
        link = ApplicationLink.objects.get()
    assert (link.from_app_id, link.to_app_id) == (award_card.id, card.id)


def test_an_award_that_funds_nothing_here_is_not_added(agency_a, membership_a) -> None:
    programme, (award,) = _pack(agency_a, membership_a, awards=[("Elsewhere", SEP, {})])
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            funding_card={"scope": "INSTITUTION", "route": SEP},
        )
        add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        assert not Application.objects.filter(candidate=award).exists()


def test_another_student_in_the_same_tenant_is_never_linked(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a,
            user=get_user_model().objects.create_user(username="student-a2"),
            role=Membership.Role.STUDENT,
        )
    spec = [("SI Scholarship", SEP, {})]
    mine, _ = _pack(agency_a, membership_a, awards=spec)
    theirs, (their_award,) = _pack(agency_a, other, awards=spec)
    with tenant_scope(agency_a.id):
        # My programme is on the board first; then their award is added directly.
        add_application(student=membership_a, candidate_id=mine.id, actor=membership_a)
        add_application(student=other, candidate_id=their_award.id, actor=other)
        pairs = {
            (link.from_app.student_id, link.to_app.student_id)
            for link in ApplicationLink.objects.select_related("from_app", "to_app")
        }
        assert pairs == {(membership_a.id, membership_a.id)}
        # And the other way: their programme links only to their own award.
        add_application(student=other, candidate_id=theirs.id, actor=other)
        pairs = {
            (link.from_app.student_id, link.to_app.student_id)
            for link in ApplicationLink.objects.select_related("from_app", "to_app")
        }
        assert pairs == {(membership_a.id, membership_a.id), (other.id, other.id)}


def _two_programmes_one_hand_added_award(agency, membership):
    run = make_run(agency, membership)
    first = make_db_candidate(agency, run, program_name="MSc Chemistry")
    second = make_db_candidate(agency, run, program_name="MSc Physics")
    award = _award(agency, run, "Hand added", SEP, confidence="LOW")
    make_published_pack(agency, run, (first, second, award))
    return first, second, award


def test_a_hand_added_award_links_to_a_programme_added_later(agency_a, membership_a) -> None:
    first, second, award = _two_programmes_one_hand_added_award(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=first.id, actor=membership_a)
        add_application(student=membership_a, candidate_id=award.id, actor=membership_a)
        add_application(student=membership_a, candidate_id=second.id, actor=membership_a)
        assert Application.objects.filter(candidate=award).count() == 1
        assert ApplicationLink.objects.filter(from_app__candidate=award).count() == 2


def test_a_hand_added_award_links_to_programmes_added_before_and_after(
    agency_a, membership_a
) -> None:
    first, second, award = _two_programmes_one_hand_added_award(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=award.id, actor=membership_a)
        add_application(student=membership_a, candidate_id=first.id, actor=membership_a)
        add_application(student=membership_a, candidate_id=second.id, actor=membership_a)
        assert Application.objects.count() == 3
        assert ApplicationLink.objects.filter(from_app__candidate=award).count() == 2


def test_a_removed_award_is_rejected_and_not_added_again(agency_a, membership_a) -> None:
    from apps.concierge.models import Notification
    from apps.funding.models import StudentDecision
    from apps.portals.applications import remove_application

    run = make_run(agency_a, membership_a)
    first = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    second = make_db_candidate(agency_a, run, program_name="MSc Physics")
    award = _award(agency_a, run, "Chevening", SEP)
    make_published_pack(agency_a, run, (first, second, award))
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=first.id, actor=membership_a)
        remove_application(Application.objects.get(candidate=award), actor=membership_a)
        tasks = Notification.objects.count()
        add_application(student=membership_a, candidate_id=second.id, actor=membership_a)
        add_application(student=membership_a, candidate_id=first.id, actor=membership_a)
        assert not Application.objects.filter(candidate=award).exists()
        assert Notification.objects.count() == tasks
        award.refresh_from_db()
        assert award.state == RecommendationCandidate.State.REJECTED
        assert StudentDecision.objects.filter(candidate=award, actor=membership_a).count() == 1


def _remove(application, actor):
    from apps.portals.applications import remove_application

    remove_application(application, actor=actor)


def test_removing_the_only_item_of_the_pack_is_refused(agency_a, membership_a) -> None:
    from apps.funding.models import AuditEvent, PackCandidate
    from apps.portals.applications import REFUSALS, ApplicationRefused

    run = make_run(agency_a, membership_a)
    award = _award(agency_a, run, "Only item", SEP)
    make_published_pack(agency_a, run, (award,))
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=award.id, actor=membership_a)
        card = Application.objects.get(candidate=award)
        audits = AuditEvent.objects.count()
        with pytest.raises(ApplicationRefused) as refused:
            _remove(card, membership_a)
        assert refused.value.reason == "last_in_pack"
        assert "only option left" in REFUSALS["last_in_pack"]
        assert Application.objects.filter(candidate=award).exists()
        assert AuditEvent.objects.count() == audits
        award.refresh_from_db()
        assert award.state == RecommendationCandidate.State.VISIBLE
        assert PackCandidate.objects.filter(candidate=award).exists()


def test_a_pack_that_changed_refuses_and_keeps_the_card(
    agency_a, membership_a, counselor_membership, monkeypatch
) -> None:
    from apps.concierge.models import Notification, RoadmapItem
    from apps.funding import services
    from apps.funding.models import AuditEvent
    from apps.funding.services import PackCommandError
    from apps.portals.applications import ApplicationRefused
    from apps.tenancy.models import CounselorAssignment

    run = make_run(agency_a, membership_a)
    first = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    award = _award(agency_a, run, "Chevening", SEP)
    make_published_pack(agency_a, run, (first, award))

    def raced(*_a, **_k):
        raise PackCommandError("the pack changed; reload")

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        add_application(student=membership_a, candidate_id=award.id, actor=membership_a)
        card = Application.objects.get(candidate=award)
        task = card.exception_item
        assert task is not None and task.state != RoadmapItem.State.DONE
        audits = AuditEvent.objects.count()
        notes = Notification.objects.count()
        monkeypatch.setattr(services, "reject_candidate", raced)
        with pytest.raises(ApplicationRefused) as refused:
            _remove(card, membership_a)
        assert refused.value.reason == "pack_changed"
        assert Application.objects.filter(candidate=award).exists()
        task.refresh_from_db()
        assert task.state != RoadmapItem.State.DONE
        assert AuditEvent.objects.count() == audits
        assert not AuditEvent.objects.filter(event="application.removed").exists()
        assert Notification.objects.count() == notes
        award.refresh_from_db()
        assert award.state == RecommendationCandidate.State.VISIBLE


def test_an_award_outside_the_pack_is_rejected_directly(agency_a, membership_a) -> None:
    from apps.funding.models import StudentDecision

    run = make_run(agency_a, membership_a)
    first = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    award = _award(agency_a, run, "Other options", SEP)
    make_published_pack(agency_a, run, (first,))
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=award.id, actor=membership_a)
        _remove(Application.objects.get(candidate=award), membership_a)
        award.refresh_from_db()
        assert award.state == RecommendationCandidate.State.REJECTED
        assert StudentDecision.objects.filter(candidate=award).count() == 1


def test_a_counsellors_remove_is_recorded_under_the_counsellor(
    agency_a, membership_a, counselor_membership
) -> None:
    from apps.funding.models import AuditEvent, StudentDecision

    run = make_run(agency_a, membership_a)
    first = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    award = _award(agency_a, run, "Chevening", SEP)
    make_published_pack(agency_a, run, (first, award))
    with tenant_scope(agency_a.id):
        add_application(student=membership_a, candidate_id=award.id, actor=membership_a)
        _remove(Application.objects.get(candidate=award), counselor_membership)
        decision = StudentDecision.objects.get(candidate=award)
        event = AuditEvent.objects.get(event="candidate.rejected", object_id=award.id)
    assert decision.actor_id == counselor_membership.id
    assert event.actor_id == counselor_membership.id


from apps.portals.award_links import award_lines  # noqa: E402


def test_lines_say_what_the_student_does(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[
        ("Automatic waiver", "AUTOMATIC_ON_ADMISSION", {}),
        ("Merit scholarship", "CONSIDERED_WITH_ADMISSION", {}),
        ("Dean's award", "INSTITUTION_NOMINATES", {}),
        ("EMJM scholarship", "JOINT_SELECTION", {}),
        ("Mystery fund", "UNSTATED", {}),
    ])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        lines = {line.name: (line.kind, line.text) for line in award_lines(card)}
    assert lines == {
        "Automatic waiver": ("AUTOMATIC", "Considered automatically — nothing to do"),
        "Merit scholarship": (
            "SAME_APPLICATION", "Considered with your application — nothing extra to submit",
        ),
        "Dean's award": ("NOMINATED", "Nominated by the university — you cannot apply for it"),
        "EMJM scholarship": ("COMBINED", "Programme + scholarship, one application"),
        "Mystery fund": ("NOT_STATED", "How to apply for this is not stated — open its page"),
    }


def test_possibly_eligible_separate_award_is_a_suggestion(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[
        ("SI Scholarship", SEP, {"confidence": "LOW"}),
    ])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        (line,) = award_lines(card)
    assert (line.kind, line.text) == (
        "SUGGESTED", "Suggested for this programme — check you qualify, then add it",
    )


def test_an_award_already_on_the_board_is_not_a_line(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[("SI Scholarship", SEP, {})])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        assert award_lines(card) == []


def test_a_rejected_award_is_never_a_line(agency_a, membership_a) -> None:
    run = make_run(agency_a, membership_a)
    first = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    second = make_db_candidate(agency_a, run, program_name="MSc Physics")
    award = _award(agency_a, run, "Chevening", SEP)
    make_published_pack(agency_a, run, (first, second, award))
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=first.id, actor=membership_a)
        _remove(Application.objects.get(candidate=award), membership_a)
        award.refresh_from_db()
        assert award.state == RecommendationCandidate.State.REJECTED
        assert award_lines(card) == []


def test_lines_never_use_internal_words(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[(n, r, {}) for n, r in [
        ("A", "AUTOMATIC_ON_ADMISSION"), ("B", "CONSIDERED_WITH_ADMISSION"),
        ("C", "INSTITUTION_NOMINATES"), ("D", "JOINT_SELECTION"), ("E", "UNSTATED"),
    ]])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        text = " ".join(line.text for line in award_lines(card)).casefold()
    assert text
    for word in ("award", "holder", "route", "_"):
        assert word not in text


def test_a_not_eligible_separate_award_is_never_a_line(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[
        ("Ineligible", SEP, {"eligible": False}),
        ("Maybe", SEP, {"confidence": "LOW"}),
    ])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        assert [line.name for line in award_lines(card)] == ["Maybe"]


def test_lines_are_sorted_by_name_ignoring_case(agency_a, membership_a) -> None:
    programme, _ = _pack(agency_a, membership_a, awards=[
        (name, "UNSTATED", {}) for name in ("zeta fund", "Beta fund", "alpha fund", "Gamma fund")
    ])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        names = [line.name for line in award_lines(card)]
    assert names == ["alpha fund", "Beta fund", "Gamma fund", "zeta fund"]


def test_a_double_submitted_direct_remove_writes_one_decision(agency_a, membership_a) -> None:
    from apps.funding.models import AuditEvent, StudentDecision
    from apps.funding.services import reject_for_student

    run = make_run(agency_a, membership_a)
    first = make_db_candidate(agency_a, run, program_name="MSc Chemistry")
    award = _award(agency_a, run, "Other options", SEP)
    make_published_pack(agency_a, run, (first,))
    with tenant_scope(agency_a.id):
        one = RecommendationCandidate.objects.get(id=award.id)
        two = RecommendationCandidate.objects.get(id=award.id)  # a stale second copy
        reject_for_student(one, student=membership_a, actor=membership_a)
        reject_for_student(two, student=membership_a, actor=membership_a)
        assert StudentDecision.objects.filter(candidate=award).count() == 1
        rejected = AuditEvent.objects.filter(event="candidate.rejected", object_id=award.id)
        assert rejected.count() == 1


def test_reject_for_student_refuses_another_students_candidate(
    agency_a, membership_a, counselor_membership
) -> None:
    from apps.funding.services import PackCommandError, reject_for_student

    run = make_run(agency_a, membership_a)
    award = _award(agency_a, run, "Mine", SEP)
    with tenant_scope(agency_a.id), pytest.raises(PackCommandError):
        reject_for_student(award, student=counselor_membership, actor=counselor_membership)
    award.refresh_from_db()
    assert award.state == RecommendationCandidate.State.VISIBLE


def test_an_add_that_lost_the_race_to_a_remove_makes_no_card(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import award_links

    programme, (award,) = _pack(agency_a, membership_a, awards=[("SI Scholarship", SEP, {})])
    with tenant_scope(agency_a.id):
        stale = RecommendationCandidate.objects.get(id=award.id)  # still VISIBLE in memory
        RecommendationCandidate.objects.filter(id=award.id).update(
            state=RecommendationCandidate.State.REJECTED
        )
        monkeypatch.setattr(award_links, "_run_pool", lambda _c: [stale])
        add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        assert not Application.objects.filter(candidate=award).exists()
        assert not ApplicationLink.objects.exists()


def test_linking_to_a_card_removed_under_us_does_not_500(agency_a, membership_a) -> None:
    from apps.portals import award_links

    programme, (award,) = _pack(agency_a, membership_a, awards=[("SI Scholarship", SEP, {})])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        award_card = Application.objects.get(candidate=award)
        ApplicationLink.objects.all().delete()
        gone = Application.objects.get(id=award_card.id)
        award_card.delete()  # the Remove committed between Add's read and the link
        award_links._link(gone, card)
        assert not ApplicationLink.objects.exists()


def test_a_concurrent_award_add_returns_the_card_the_other_request_made(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import award_links

    programme, (award,) = _pack(agency_a, membership_a, awards=[("SI Scholarship", SEP, {})])
    with tenant_scope(agency_a.id):
        card = add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
        ApplicationLink.objects.all().delete()
        real = award_links._board
        monkeypatch.setattr(
            award_links, "_board",
            lambda student: {k: v for k, v in real(student).items() if k != award.id},
        )
        award_links.link_awards(card, actor=membership_a)
        assert Application.objects.filter(candidate=award).count() == 1
        assert ApplicationLink.objects.count() == 1


def test_the_award_lock_does_not_block_foreign_key_checks(agency_a, membership_a) -> None:
    """FOR UPDATE on the award blocks the FOR KEY SHARE a concurrent Remove's pack copy
    takes, and the two requests deadlock. NO KEY UPDATE still conflicts with the reject's
    state UPDATE. Asserted on the SQL: a two-thread probe needs real commits and is flaky."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    programme, _ = _pack(agency_a, membership_a, awards=[("SI Scholarship", SEP, {})])
    with tenant_scope(agency_a.id), CaptureQueriesContext(connection) as queries:
        add_application(student=membership_a, candidate_id=programme.id, actor=membership_a)
    locks = [q["sql"] for q in queries if "FOR " in q["sql"] and "UPDATE" in q["sql"]]
    assert locks and all("FOR NO KEY UPDATE" in sql for sql in locks)
