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
        content=_CONTENT,
        claim_verdicts=(),
        retried=True,
        binding_violation_after_retry=True,
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
    assert draft.application_id == card.id
    assert draft.destination_label
    assert draft.letter_gates == [
        {"code": "WRONG_INSTITUTION", "unit_archetype": "opening", "blocking": True}
    ]
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


def test_worker_generate_letter_for_wires_readings_storyline_research_fit_and_cohort(
    agency_a, membership_a, card
) -> None:
    from uuid import uuid4

    from apps.documents.evidence.readings import UsableReading
    from apps.documents.letter_schemas import Storyline

    reading = UsableReading(
        source="repo",
        url="https://github.com/student/mpc",
        document_id=None,
        summary="Nonlinear MPC solver in C++",
        kind="code_repository",
        names=("student",),
        first_commit="2024-01-01",
        last_commit="2025-01-01",
        bullets=(),
    )
    storyline = Storyline(
        theme="Bridging embedded MPC to real-time quadruped stability",
        theme_kind="RESEARCH",
        anchors=(uuid4(),),
        future="Doctoral research in robust legged control",
    )
    result = LetterGenerationResult(
        content=_CONTENT,
        claim_verdicts=(),
        retried=False,
        gate_violations=(),
    )
    with (
        _clear(),
        patch(f"{_W}.usable_readings", return_value=(reading,)),
        patch(f"{_W}._storyline_for", return_value=storyline) as storyline_fn,
        patch(f"{_W}._ensure_research_fit") as rf_fn,
        patch(f"{_W}._ensure_home_country_context") as hc_fn,
        patch(f"{_W}.recent_programme_sentences", return_value=frozenset({"stock sentence."})),
        patch(f"{_W}.generate_letter", return_value=result) as generate,
    ):
        handle_document_work(_message(agency_a, membership_a, card))
    storyline_fn.assert_called_once()
    rf_fn.assert_called_once()
    hc_fn.assert_called_once()
    assert generate.call_args.kwargs["storyline"] == storyline
    assert generate.call_args.kwargs["readings"] == (reading,)
    assert generate.call_args.kwargs["cohort_sentences"] == frozenset({"stock sentence."})


def test_worker_persists_non_blocking_gates_and_clean_retry_and_filters_inputs(
    agency_a, membership_a, card
) -> None:
    from uuid import uuid4

    from apps.documents.letter_worker import _applicant_name
    from apps.documents.models import NarrativeInput, VerifiedFact

    # 1. _applicant_name skips a newer passport IDENTITY fact without full_name
    f1 = VerifiedFact(
        id=uuid4(),
        category=VerifiedFact.Category.IDENTITY,
        payload={"full_name": "Leyla Memmedova"},
    )
    f2 = VerifiedFact(
        id=uuid4(),
        category=VerifiedFact.Category.IDENTITY,
        payload={"date_of_birth": "2001-05-10"},
    )
    assert _applicant_name({f1.id: f1, f2.id: f2}) == "Leyla Memmedova"

    # 2. Clean Pass-2 retry sets letter_retried=False and non-blocking gate persists blocking=False
    other_prog_id = uuid4()
    with tenant_scope(agency_a.id):
        NarrativeInput.objects.create(
            tenant=agency_a,
            student=membership_a,
            kind=NarrativeInput.Kind.RESEARCH_FIT,
            text="Foreign programme group",
            provenance={"program_id": str(other_prog_id), "entity": "Foreign Lab"},
        )
    result = LetterGenerationResult(
        content=_CONTENT,
        claim_verdicts=(),
        retried=True,
        binding_violation_after_retry=False,
        gate_violations=(
            LetterGateViolation(
                GateCode.STORYLINE_DRIFT,
                "advisory drift",
                unit_archetype="OPENING",
                blocking=False,
            ),
        ),
    )
    with (
        _clear(),
        patch(f"{_W}._storyline_for", return_value=None) as storyline_fn,
        patch(f"{_W}._ensure_research_fit"),
        patch(f"{_W}._ensure_home_country_context"),
        patch(f"{_W}.generate_letter", return_value=result),
    ):
        handle_document_work(_message(agency_a, membership_a, card))
    # Foreign programme's RESEARCH_FIT input was filtered out before _storyline_for
    passed_inputs = storyline_fn.call_args.args[3]
    assert passed_inputs == {}
    with tenant_scope(agency_a.id):
        draft = DocumentDraft.objects.get(kind=DocumentDraft.Kind.MOTIVATION_LETTER)
    assert draft.letter_retried is False
    assert draft.letter_gates == [
        {"code": "STORYLINE_DRIFT", "unit_archetype": "OPENING", "blocking": False}
    ]

    # 3. Approving reconstructs blocking=False on LetterGateViolation
    message = _message(
        agency_a, membership_a, card, action="approve_letter", draft_id=draft.id
    )
    with (
        patch(f"{_W}.mark_letter_ready", side_effect=lambda **kw: kw["document"]) as ready,
        patch(f"{_W}.render_letter"),
    ):
        handle_document_work(message)
    [reconstructed] = ready.call_args.kwargs["gate_violations"]
    assert reconstructed.blocking is False
    assert ready.call_args.kwargs["binding_violation_after_retry"] is False

    # 4. If render_letter raises PreflightBlocked, mark_letter_ready rolls back
    from apps.documents.render import PreflightBlocked

    def _approve_in_db(**kw):
        doc = kw["document"]
        doc.status = DocumentDraft.Status.APPROVED
        doc.save(update_fields=["status"])
        return doc

    with (
        patch(f"{_W}.mark_letter_ready", side_effect=_approve_in_db),
        patch(f"{_W}.render_letter", side_effect=PreflightBlocked("exceeds max_pages")),
    ):
        handle_document_work(message)
    with tenant_scope(agency_a.id):
        draft.refresh_from_db()
        card.refresh_from_db()
    assert draft.status == DocumentDraft.Status.DRAFT
    assert card.letter_note == "blocked"

    # 5. A refined draft with ungrounded factual assertions and empty claims=() is
    #    checked by ground_and_align_letter_claims + check_claim_coverage on approve
    from django.utils import timezone

    with tenant_scope(agency_a.id):
        VerifiedFact.objects.create(
            tenant=agency_a,
            student=membership_a,
            category=VerifiedFact.Category.EDUCATION,
            payload={"institution_original": "ADA University", "degree_as_awarded": "BSc"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv-1",
            confirmed_by=membership_a,
            confirmed_at=timezone.now(),
            created_by=membership_a,
        )
        refined_draft = DocumentDraft.objects.create(
            tenant=agency_a,
            student=membership_a,
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            version=2,
            programme_id=card.program_id,
            content={
                "language": "en",
                "units": [
                    {
                        "archetype": "ACADEMIC_PREPARATION",
                        "text": "In 2024 I won the Nobel Prize with a 4.0 GPA.",
                    }
                ],
            },
            letter_gates=[],
            letter_retried=False,
        )
    refined_msg = _message(
        agency_a, membership_a, card, action="approve_letter", draft_id=refined_draft.id
    )
    handle_document_work(refined_msg)
    with tenant_scope(agency_a.id):
        refined_draft.refresh_from_db()
        card.refresh_from_db()
    assert refined_draft.status == DocumentDraft.Status.DRAFT
    assert card.letter_note == "blocked"




