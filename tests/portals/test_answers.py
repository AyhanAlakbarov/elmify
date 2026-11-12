"""What students type where the co-pilot was unsure (owner, 2026-10-09)."""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope
from tests.portals.test_kit import _application
from tests.portals.test_profile_values import _fact

pytestmark = pytest.mark.django_db


def _unsure(field: str, selector: str) -> dict[str, object]:
    return {"profile_field": field, "sure": False,
            "action": {"selector": selector, "method": "fill", "arguments": ["%value%"]}}


HINTS = [
    _unsure("personal.date_of_birth", "#dob"),
    _unsure("personal.place_of_birth", "#x"),
    _unsure("personal.home_town", "#y"),
]


def _student(agency, django_user_model, name: str):
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(username=name)
    return Membership.objects.create(tenant=agency, user=user, role=Membership.Role.STUDENT)


def _answer(selector: str, value: str, kind: str = "hint"):
    from apps.portals.answers import Answer

    return Answer(selector=selector, kind=kind, value=value)


def test_a_typed_answer_is_classified_against_the_students_own_facts(
    agency_a, membership_a
) -> None:
    from apps.portals.answers import record_answers
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        _fact(agency_a, membership_a, "PERSONAL",
              {"date_of_birth": "2001-03-07", "given_name": "Leyla"})
        application = _application(agency_a, membership_a, entries=HINTS)
        mint_packet(application)  # the PACKET row names the hints
        confirmed, corrected, new = record_answers(application, [
            _answer("#dob", "2001-03-07"), _answer("#x", "leyla"), _answer("#y", "Ganja"),
        ])
    assert (confirmed.outcome, confirmed.guessed_field) == (
        "CONFIRMED_GUESS", "personal.date_of_birth",
    )
    assert (corrected.outcome, corrected.matched_field) == (
        "CORRECTED_GUESS", "personal.given_name",
    )
    assert new.outcome == "NEW_ANSWER"


def test_a_value_typed_into_a_sure_box_is_never_a_correction(agency_a, membership_a) -> None:
    """Preflight #1: only an `unsure` hint is a guess. A sure box the student
    holds no fact for (`no_fact`) records a NEW_ANSWER even when the value
    equals another of their facts, so no number of students can remap it."""
    from apps.portals.answers import record_answers
    from apps.portals.packets import mint_packet

    sure = {**_unsure("personal.home_town", "#y"), "sure": True}
    with tenant_scope(agency_a.id):
        _fact(agency_a, membership_a, "PERSONAL", {"given_name": "Leyla"})
        application = _application(agency_a, membership_a, entries=[sure])
        packet = mint_packet(application)
        assert [(h.selector, h.reason) for h in packet.hints] == [("#y", "no_fact")]
        [answer] = record_answers(application, [_answer("#y", "Leyla")])
    assert (answer.outcome, answer.guessed_field, answer.matched_field) == (
        "NEW_ANSWER", "personal.home_town", "personal.given_name",
    )


def test_only_boxes_the_packet_named_are_recorded(agency_a, membership_a) -> None:
    """The extension may send the boxes we marked, never the rest of the page,
    and a hint box is never reported as one of our filled entries. An answer
    for a box the latest PACKET does not name (a stale cached packet) is
    skipped, and the rest of the batch is still recorded."""
    from apps.portals.answers import record_answers
    from apps.portals.models import PortalAnswer
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=HINTS)
        mint_packet(application)
        saved = record_answers(application, [
            _answer("#y", "Ganja"), _answer("#nowhere", "x"), _answer("#dob", "x", kind="changed"),
        ])
        assert [a.selector for a in saved] == ["#y"]
        assert list(PortalAnswer.objects.values_list("selector", flat=True)) == ["#y"]


@pytest.mark.parametrize("selector", ["#password", "input[name=user_passwd]", "#pwd"])
def test_a_password_box_refuses_the_whole_batch(agency_a, membership_a, selector) -> None:
    from apps.portals.answers import AnswerRefused, record_answers
    from apps.portals.models import PortalAnswer
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=HINTS)
        mint_packet(application)
        with pytest.raises(AnswerRefused):
            record_answers(application, [_answer("#y", "Ganja"), _answer(selector, "secret")])
        assert not PortalAnswer.objects.exists()  # a refused batch writes nothing


def test_a_changed_entry_records_the_field_the_packet_typed(agency_a, membership_a) -> None:
    from apps.portals.answers import record_answers
    from apps.portals.packets import mint_packet

    entry = {**_unsure("personal.given_name", "#gn"), "sure": True}
    with tenant_scope(agency_a.id):
        _fact(agency_a, membership_a, "PERSONAL", {"given_name": "Leyla"})
        application = _application(agency_a, membership_a, entries=[entry])
        mint_packet(application)
        [answer] = record_answers(application, [_answer("#gn", "Leyla A.", kind="changed")])
    assert (answer.outcome, answer.guessed_field) == ("CHANGED_OUR_VALUE", "personal.given_name")


def _tenant_form(agency):
    from apps.portals.models import FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"answers-{uuid4()}",
        form_url="https://apply.example.edu/personal",
    )
    FieldMap.objects.create(portal_form=form, version=1, learned_by_tenant=agency,
                            entries=[_unsure("personal.date_of_birth", "#dob")])
    return form


def _answered(agency, form, student, outcome: str, matched: str = "") -> None:
    from apps.portals.models import PortalAnswer

    PortalAnswer.objects.create(
        tenant=agency, student=student, portal_form=form, selector="#dob",
        guessed_field="personal.date_of_birth", matched_field=matched, value="v",
        outcome=outcome,
    )


def test_three_students_confirming_a_guess_make_it_sure(agency_a, django_user_model) -> None:
    from apps.portals.answers import learn_from_answers

    with tenant_scope(agency_a.id):
        form = _tenant_form(agency_a)
        for name in ("s1", "s2"):
            _answered(agency_a, form, _student(agency_a, django_user_model, name),
                      "CONFIRMED_GUESS")
        assert learn_from_answers(form, agency_a.id) is None  # two is not three
        _answered(agency_a, form, _student(agency_a, django_user_model, "s3"),
                  "CONFIRMED_GUESS")
        new_map = learn_from_answers(form, agency_a.id)
        assert learn_from_answers(form, agency_a.id) is None  # learned once, not every call
    assert new_map is not None and new_map.learned_by_tenant_id == agency_a.id
    [entry] = new_map.entries
    assert entry["sure"] is True
    # A map holds which field a box asks for, never what anyone typed.
    assert set(entry) == {"profile_field", "sure", "action"}
    assert entry["action"]["arguments"] == ["%value%"]


def test_one_student_confirming_three_times_is_one_confirmation(
    agency_a, membership_a
) -> None:
    from apps.portals.answers import learn_from_answers

    with tenant_scope(agency_a.id):
        form = _tenant_form(agency_a)
        for _ in range(3):
            _answered(agency_a, form, membership_a, "CONFIRMED_GUESS")
        assert learn_from_answers(form, agency_a.id) is None


def test_two_students_correcting_a_guess_remap_the_box(agency_a, django_user_model) -> None:
    from apps.portals.answers import learn_from_answers

    with tenant_scope(agency_a.id):
        form = _tenant_form(agency_a)
        for name in ("s1", "s2"):
            _answered(agency_a, form, _student(agency_a, django_user_model, name),
                      "CORRECTED_GUESS", matched="personal.given_name")
        new_map = learn_from_answers(form, agency_a.id)
    assert new_map is not None
    [entry] = new_map.entries
    assert (entry["profile_field"], entry["sure"]) == ("personal.given_name", True)


def test_a_shared_map_is_never_changed_by_answers(agency_a, membership_a) -> None:
    from apps.portals.answers import learn_from_answers

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=HINTS)  # shared v1
        assert learn_from_answers(application.portal_form, agency_a.id) is None


def test_a_students_own_answer_is_typed_back_for_them_only(
    agency_a, membership_a, django_user_model
) -> None:
    from apps.portals.answers import record_answers
    from apps.portals.models import Application
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=HINTS)
        mint_packet(application)
        record_answers(application, [_answer("#y", "Ganja")])
        mine = mint_packet(application)
        other = Application.objects.create(
            tenant=agency_a, student=_student(agency_a, django_user_model, "other"),
            program_id=uuid4(), portal_form=application.portal_form,
        )
        theirs = mint_packet(other)
    [own] = [e for e in mine.entries if e.selector == "#y"]
    assert (own.value, own.from_answer, own.profile_field) == (
        "Ganja", True, "personal.home_town",
    )
    assert "#y" not in {h.selector for h in mine.hints}
    assert not any(e.value == "Ganja" for e in theirs.entries)
    assert "#y" in {h.selector for h in theirs.hints}


def test_an_answer_is_typed_back_only_into_the_question_it_answered(
    agency_a, membership_a
) -> None:
    """Preflight #2: a portal that re-orders its form gives an old selector a new
    question. The answer goes back only where box AND field both match."""
    from apps.portals.answers import record_answers
    from apps.portals.models import FieldMap
    from apps.portals.packets import mint_packet

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=HINTS)
        mint_packet(application)
        record_answers(application, [_answer("#y", "Ganja")])
        form = application.portal_form
        FieldMap.objects.get(portal_form=form, version=1).supersede()
        FieldMap.objects.create(portal_form=form, version=2,
                                entries=[_unsure("personal.place_of_birth", "#y")])
        packet = mint_packet(application)
    assert not any(e.value == "Ganja" for e in packet.entries)
    assert [(h.selector, h.profile_field) for h in packet.hints] == [
        ("#y", "personal.place_of_birth"),
    ]


def test_erasure_deletes_the_students_answers(agency_a, django_user_model, monkeypatch) -> None:
    """The delete runs inside advance_deletion's set_local_tenant block. The test
    role is BYPASSRLS, so this proves the delete exists, not its RLS placement."""
    from django.utils import timezone

    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy
    from apps.portals.models import PortalAnswer

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "erased")
        _answered(agency_a, _tenant_form(agency_a), student, "NEW_ANSWER")
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        for state in ("RETENTION_REVIEW", "APPROVED", "EXECUTED"):
            advance_deletion(request, state)
        assert not PortalAnswer.objects.filter(student_id=student.id).exists()


def test_the_answers_route_records_and_refuses_the_unnamed(
    client, agency_a, domain_a, membership_a
) -> None:
    import json

    from apps.funding.models import AuditEvent
    from apps.portals.packets import mint_packet
    from tests.portals.test_ext_api import _pair

    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=HINTS)
        mint_packet(application)
    token = _pair(client, agency_a, membership_a, domain_a)

    def post(answers: list[dict[str, str]]):
        return client.post(
            f"/ext/applications/{application.id}/answers",
            data=json.dumps({"answers": answers}), content_type="application/json",
            HTTP_HOST=domain_a.host, HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    assert post([{"selector": "#y", "kind": "hint", "value": "Ganja"}]).json() == {
        "recorded": 1, "skipped": 0,
    }
    stale = post([{"selector": "#nowhere", "kind": "hint", "value": "x"}])
    assert (stale.status_code, stale.json()) == (201, {"recorded": 0, "skipped": 1})
    refused = post([{"selector": "#password", "kind": "hint", "value": "x"}])
    assert (refused.status_code, refused.json()["error"]) == (400, "invalid_answers")
    too_many = post([{"selector": "#y", "kind": "hint", "value": "x"}] * 101)
    assert (too_many.status_code, too_many.json()["error"]) == (400, "invalid_answers")
    long_essay = "Why I want to study this programme. " * 60
    assert post([{"selector": "#y", "kind": "hint", "value": long_essay}]).json() == {
        "recorded": 1, "skipped": 0,
    }
    too_long = post([{"selector": "#y", "kind": "hint", "value": "x" * 10_001}])
    assert (too_long.status_code, too_long.json()["error"]) == (400, "invalid_answers")
    with tenant_scope(agency_a.id):
        events = list(AuditEvent.objects.filter(event="portal.answers_recorded"))
    assert len(events) == 3  # the three batches the server accepted
    assert "Ganja" not in json.dumps(
        [{k: str(v) for k, v in e.__dict__.items() if not k.startswith("_")} for e in events]
    )


def test_a_value_matching_a_degree_names_the_indexed_key_not_the_unindexed(
    agency_a, membership_a
) -> None:
    from apps.documents.models import VerifiedFact
    from apps.portals.answers import _match
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        for degree, start in (("BSc", "2018-09"), ("MSc", "2022-09")):
            _fact(agency_a, membership_a, VerifiedFact.Category.EDUCATION,
                  {"degree_as_awarded": degree, "start_date": start})
        facts = verified_values(membership_a)
    # The unindexed key is the last row written, here the same value as degree 2.
    assert facts["education.degree_as_awarded"] == "MSc"
    assert _match(facts, "personal.given_name", "MSc") == "education.2.degree_as_awarded"


def test_unsure_narrative_answers_match_narrative_values_and_confirm_guess(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import answers as answers_mod
    from apps.portals.answers import Answer, record_answers
    from apps.portals.models import PortalAnswer
    from apps.portals.packets import mint_packet

    entries = [
        {
            "profile_field": "narrative.career_plan",
            "sure": False,
            "action": {
                "selector": "#career",
                "description": "Career plan after graduation",
                "method": "fill",
                "arguments": ["%value%"],
            },
        }
    ]
    career_text = "To return to Baku and build clean water infrastructure."
    monkeypatch.setattr(
        answers_mod,
        "narrative_values",
        lambda student, **kw: {"narrative.career_plan": career_text},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=entries)
        mint_packet(application)
        saved = record_answers(
            application,
            [Answer(selector="#career", kind="hint", value=career_text)],
        )

    assert len(saved) == 1
    assert saved[0].outcome == PortalAnswer.Outcome.CONFIRMED_GUESS
    assert saved[0].matched_field == "narrative.career_plan"
