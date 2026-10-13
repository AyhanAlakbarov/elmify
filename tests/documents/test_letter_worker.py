"""The letter's worker branch: refusals become a code on the card, a letter
becomes a draft carrying its own gate record, and approval reads that record."""

from unittest.mock import patch

import pytest

from apps.documents.document_queue import DocumentWorkMessage
from apps.documents.document_worker import handle_document_work
from apps.documents.letter_gates import GateCode, LetterGateViolation
from apps.documents.letter_schemas import LetterContent, LetterUnit
from apps.documents.letter_shape import NotGeneratable
from apps.documents.letters import LetterGenerationResult
from apps.documents.models import DocumentDraft
from apps.research.provenance import Verdict
from apps.tenancy.context import tenant_scope
from tests.dashboard import conftest as dashboard_conftest
from tests.dashboard.conftest import add_card

pytestmark = pytest.mark.django_db
pack = dashboard_conftest.pack
_W = "apps.documents.letter_worker"
_CONTENT = LetterContent(
    language="en", units=(LetterUnit(archetype="opening", text="Why this programme."),)
)


def _message(agency, student, application, **fields):
    return DocumentWorkMessage(
        action=fields.pop("action", "generate"), kind="MOTIVATION_LETTER",
        tenant_id=agency.id, student_id=student.id, application_id=application.id,
        programme_id=application.program_id, **fields,
    )


@pytest.fixture
def card(agency_a, membership_a, pack):
    programme, _award = pack
    with tenant_scope(agency_a.id):
        return add_card(agency_a, membership_a, programme, letter_state="QUEUED")


def _clear():
    return patch(f"{_W}.programme_verdict", return_value=(Verdict.RECOGNISED, "ok"))


def test_a_written_letter_becomes_a_draft_with_its_gate_record(
    agency_a, membership_a, card
) -> None:
    result = LetterGenerationResult(
        content=_CONTENT, claim_verdicts=(), retried=True,
        gate_violations=(
            LetterGateViolation(GateCode.WRONG_INSTITUTION, "names TUM", unit_archetype="opening"),
        ),
    )
    with _clear(), patch(f"{_W}.generate_letter", return_value=result) as generate:
        handle_document_work(_message(agency_a, membership_a, card))
    assert generate.call_args.kwargs["student"].id == membership_a.id
    with tenant_scope(agency_a.id):
        draft = DocumentDraft.objects.get(kind=DocumentDraft.Kind.MOTIVATION_LETTER)
        card.refresh_from_db()
    assert draft.programme_id == card.program_id
    assert draft.letter_gates == [{"code": "WRONG_INSTITUTION", "unit_archetype": "opening"}]
    assert draft.letter_retried is True
    assert draft.letter_cycle  # the prompt the letter was written to
    assert (card.letter_state, card.letter_note) == ("", "")


def test_a_refusal_is_a_code_on_the_card_and_no_draft(agency_a, membership_a, card) -> None:
    refusal = NotGeneratable("naming required, no confirmed fit")
    with _clear(), patch(f"{_W}.generate_letter", side_effect=refusal):
        handle_document_work(_message(agency_a, membership_a, card))
    with tenant_scope(agency_a.id):
        card.refresh_from_db()
        assert not DocumentDraft.objects.exists()
    assert (card.letter_state, card.letter_note) == ("REFUSED", "needs_research_fit")


def test_a_blocked_body_gets_no_letter(agency_a, membership_a, card) -> None:
    with patch(f"{_W}.programme_verdict", return_value=(Verdict.BLOCKED, "x")), patch(
        f"{_W}.generate_letter"
    ) as generate:
        handle_document_work(_message(agency_a, membership_a, card))
    generate.assert_not_called()
    with tenant_scope(agency_a.id):
        card.refresh_from_db()
    assert card.letter_note == "programme_blocked"


def test_approval_hands_the_generators_gate_record_to_mark_letter_ready(
    agency_a, membership_a, card
) -> None:
    with tenant_scope(agency_a.id):
        draft = DocumentDraft.objects.create(
            tenant=agency_a, student=membership_a, kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            version=1, programme_id=card.program_id, content=_CONTENT.model_dump(mode="json"),
            letter_gates=[{"code": "LANGUAGE_MISMATCH", "unit_archetype": None}],
            letter_retried=False,
        )

    def _flag(**kwargs):
        return kwargs["document"]  # a counsellor flag: the draft stays a draft

    message = _message(agency_a, membership_a, card, action="approve_letter", draft_id=draft.id)
    with patch(f"{_W}.mark_letter_ready", side_effect=_flag) as ready, patch(
        f"{_W}.render_letter"
    ) as render:
        handle_document_work(message)
    gates = ready.call_args.kwargs["gate_violations"]
    assert [g.code for g in gates] == [GateCode.LANGUAGE_MISMATCH]
    assert ready.call_args.kwargs["accepted_by"].id == membership_a.id
    render.assert_not_called()
    with tenant_scope(agency_a.id):
        card.refresh_from_db()
    assert card.letter_note == "flagged"
