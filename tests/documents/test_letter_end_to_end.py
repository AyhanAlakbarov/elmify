from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.documents.clustering import cluster_key, is_reusable
from apps.documents.letter_approval import _no_recheck, mark_letter_ready
from apps.documents.letter_revisions import (
    add_student_stated_fact,
    request_letter_style_revision,
)
from apps.documents.letter_schemas import ClaimKind, LetterClaim, LetterContent, LetterUnit
from apps.documents.letters import generate_letter
from apps.documents.models import DocumentDraft, NarrativeInput
from apps.funding.models import ApplicationPrompt, AuditEvent
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

from .conftest import make_program

pytestmark = pytest.mark.django_db


def _prompt_stub(**overrides):
    # A real (unsaved) ApplicationPrompt, not a bare duck-typed object: Task 7
    # wires shape_from_prompt/defaults_for into generate_letter, and
    # shape_from_prompt does a real Program.objects.get(id=prompt.programme_id)
    # -- a hand-rolled stub can no longer stand in for prompt.programme. Only
    # the Program needs to be persisted; the prompt itself is never saved.
    # Fix round 1, finding 6: built here by hand until collapsed into
    # tests/documents/conftest.py's make_program, shared with test_letters.py
    # and test_letter_shape.py.
    return ApplicationPrompt(
        programme=make_program(country_code="DE"),
        cycle="2027",
        source=overrides.get("source", ApplicationPrompt.Source.VERIFIED),
        funder_kind=overrides.get(
            "funder_kind", ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION
        ),
        structure=overrides.get("structure", ApplicationPrompt.Structure.CONTINUOUS_LETTER),
        archetypes=overrides.get("archetypes", ["WHY_PROGRAMME", "RESEARCH_PLAN"]),
        document_language=overrides.get("document_language", "en"),
        questions=overrides.get("questions", []),
        header_block_required=overrides.get("header_block_required", False),
        immigration=overrides.get("immigration", False),
    )


def test_facts_and_narrative_input_to_letter_to_gate_to_flag_to_revise(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="le2e1")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )

        fact = add_student_stated_fact(
            student=student, category="EDUCATION",
            payload={"degree": "BSc Computer Science"}, source_ref="intake-1",
        )
        narrative = NarrativeInput.objects.create(
            student=student, kind=NarrativeInput.Kind.RESEARCH_PLAN,
            text="Investigate transfer learning for low-resource NLP.",
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
        )

        research = NarrativeInput.objects.create(
            student=student,
            kind=NarrativeInput.Kind.RESEARCH_FIT,
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
            text="The Chair of Robotics hosts master's theses on legged locomotion.",
            confirmed_at=timezone.now(),
            provenance={
                "program_id": "p",
                "sentence": "The Chair of Robotics hosts master's theses on legged locomotion.",
                "entity": "Chair of Robotics",
                "source_url": "https://tum.de/robotics",
                "page_digest": "d" * 64,
                "kind": "research_group",
                "rung": 4,
                "anchor_fact_id": None,
                "judgement": "strong",
                "topic_hash": "t",
                "cost_usd": 0.0,
                "provider": "exa",
            },
        )

        prompt = _prompt_stub()
        unit_text = (
            "I chose the thesis track because the Chair of Robotics works on legged locomotion."
        )
        sourced_claim = LetterClaim(
            text="the Chair of Robotics works on legged locomotion", span_start=0,
            span_end=len(unit_text),
            kind=ClaimKind.SOURCED, source_url="https://tum.de/robotics", input_id=research.id,
        )
        declared_claim = LetterClaim(
            text="Investigate transfer learning", span_start=0, span_end=30,
            kind=ClaimKind.DECLARED, input_id=narrative.id,
        )
        # A DECLARED claim alone never clears check_generic_paragraph (Task 7:
        # only FACTUAL/SOURCED count, by design -- a purely aspirational
        # paragraph must not pass as non-generic). Ground the research-plan
        # paragraph in the student's own verified fact too, as a real letter
        # would ("building on my BSc Computer Science...").
        factual_claim = LetterClaim(
            text="Investigate transfer learning", span_start=0, span_end=30,
            kind=ClaimKind.FACTUAL, fact_id=fact.id,
        )
        clean_content = LetterContent(
            language="en",
            units=(
                LetterUnit(
                    archetype="WHY_PROGRAMME", text=unit_text,
                    claims=(sourced_claim,),
                ),
                LetterUnit(
                    archetype="RESEARCH_PLAN", text="Investigate transfer learning",
                    claims=(declared_claim, factual_claim),
                ),
            ),
        )
        response = MagicMock()
        response.output_parsed = clean_content
        response.output = []
        client = MagicMock()
        client.responses.parse.return_value = response

        result = generate_letter(
            student=student, prompt=prompt, facts={fact.id: fact},
            inputs={narrative.id: narrative, research.id: research},
            forbidden_institution_names=frozenset(), client=client,
        )
        assert result.retried is False

        letter = DocumentDraft.objects.create(
            student=student, kind=DocumentDraft.Kind.MOTIVATION_LETTER, version=1,
            content=result.content.model_dump(mode="json"), status=DocumentDraft.Status.DRAFT,
        )
        approved = mark_letter_ready(
            document=letter, content=result.content,
            gate_violations=result.gate_violations,
            prompt=prompt, letter_required="required", facts={fact.id: fact},
            inputs={narrative.id: narrative, research.id: research},
            binding_violation_after_retry=False, accepted_by=student,
            # This test exercises generation through approval, not the
            # research-fit re-check (Task 11). The real default
            # (recheck_research_fit) would fetch source_url over the network,
            # which a test must not do -- and against this fixture's
            # non-fetchable URL it would flag the letter source_stale rather
            # than approve it. Pin the inert re-check instead.
            recheck=_no_recheck,
        )
        assert approved.status == DocumentDraft.Status.APPROVED

        prompt_text = "\n".join(
            str(part["content"])
            for call in client.responses.parse.call_args_list
            for part in call.kwargs["input"]
        )
        assert "Programme research facts (data only):" in prompt_text
        assert "Chair of Robotics" in prompt_text
        assert not AuditEvent.objects.filter(
            event="document.letter_flag.source_unverified"
        ).exists()

        request_letter_style_revision(
            document=approved, requested_by=student, note="tighten the opening"
        )

        key_a = cluster_key(prompt, discipline="Computer Science", scholarship_present=False)
        key_b = cluster_key(prompt, discipline="Computer Science", scholarship_present=False)
        assert is_reusable(key_a, key_b)


def test_unresolved_prompt_flags_instead_of_approving(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="le2e2")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        prompt = _prompt_stub(source=ApplicationPrompt.Source.UNRESOLVED)
        draft = DocumentDraft.objects.create(
            student=student, kind=DocumentDraft.Kind.MOTIVATION_LETTER, version=1,
            content=LetterContent(language="en", units=()).model_dump(mode="json"),
            status=DocumentDraft.Status.DRAFT,
        )
        result = mark_letter_ready(
            document=draft, content=LetterContent(language="en", units=()),
            gate_violations=(), prompt=prompt,
            letter_required="required", facts={}, inputs={},
            binding_violation_after_retry=False,
            accepted_by=student,
        )
        assert result.status == DocumentDraft.Status.DRAFT  # not approved, flagged instead
