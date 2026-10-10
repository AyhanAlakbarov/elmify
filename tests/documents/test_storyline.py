from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from apps.documents.letter_schemas import Storyline
from apps.documents.models import VerifiedFact
from apps.documents.storyline import (
    StorylineCandidates,
    StorylineProposalFailure,
    StorylineRateLimited,
    ThemeKind,
    _facts_payload,
    choose_storyline,
    propose_storylines,
    theme_kind_for,
)
from apps.funding.models import ApplicationPrompt
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


class _Fact:
    def __init__(self, category, payload=None):
        self.category = category
        self.payload = payload if payload is not None else {}


def _facts(*categories):
    return {uuid4(): _Fact(c) for c in categories}


def _story(anchors, *, theme="theme", assumptions=(), turn=None):
    return Storyline(
        theme=theme,
        theme_kind="PLAN",
        anchors=tuple(anchors),
        turn=turn,
        assumptions=tuple(assumptions),
        future="f",
    )


def _mock_client(candidates):
    client = MagicMock()
    response = MagicMock()
    response.output_parsed = candidates
    client.responses.parse.return_value = response
    return client


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency,
        user=user,
        role=Membership.Role.STUDENT,
        active=True,
        application_email=f"{name}@applications.example",
    )


def test_theme_kind_by_reader():
    K = ApplicationPrompt.FunderKind
    assert theme_kind_for(K.RESEARCH_SUPERVISOR, ()) == ThemeKind.PROBLEM
    assert theme_kind_for(K.UNIVERSITY_ADMISSION, ("RESEARCH_PLAN",)) == ThemeKind.PROBLEM
    assert theme_kind_for(K.UNIVERSITY_ADMISSION, ("WHY_PROGRAMME",)) == ThemeKind.MATCH
    assert theme_kind_for(K.GOVERNMENT_SCHOLARSHIP, ()) == ThemeKind.PLAN
    assert theme_kind_for(K.IMMIGRATION_AUTHORITY, ()) is None


def test_candidate_with_unknown_anchor_is_dropped():
    facts = _facts("EDUCATION", "EXPERIENCE")
    bad = _story([uuid4()])
    good = _story(list(facts))
    candidates = StorylineCandidates(candidates=(bad, good))
    chosen = choose_storyline(candidates, facts=facts, recent_themes=())
    assert chosen == good


def test_fewer_assumptions_wins_at_equal_evidence():
    facts = _facts("EDUCATION", "EXPERIENCE", "AWARD")
    ids = list(facts)
    invented = _story(ids, theme="a", assumptions=("x", "y"))
    grounded = _story(ids, theme="b", assumptions=("x",))
    candidates = StorylineCandidates(candidates=(invented, grounded))
    chosen = choose_storyline(candidates, facts=facts, recent_themes=())
    assert chosen == grounded


def test_rarer_theme_wins_a_tie():
    facts = _facts("EDUCATION", "EXPERIENCE", "AWARD")
    ids = list(facts)
    common = _story(ids, theme="from building systems to understanding why they scale")
    rare = _story(ids, theme="a grade that fell and what it turned out to be measuring")
    recent = ("from building things to understanding why they scale",)
    candidates = StorylineCandidates(candidates=(common, rare))
    chosen = choose_storyline(candidates, facts=facts, recent_themes=recent)
    assert chosen == rare


def test_turn_outside_anchors_is_dropped():
    facts = _facts("EDUCATION", "EXPERIENCE")
    ids = list(facts)
    stray = _story(ids, turn=uuid4())
    candidates = StorylineCandidates(candidates=(stray,))
    assert choose_storyline(candidates, facts=facts, recent_themes=()) is None


def test_propose_labels_data_and_is_rate_limited(agency_a, django_user_model):
    # Stubs the parser the way tests/documents/test_generation.py stubs the
    # generation call: a MagicMock whose response.output_parsed is the typed
    # payload, and the rate limit is exercised for real against the cache
    # rather than mocking rate_limited itself (same pattern as
    # test_generate_cv_rate_limited).
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "storyline-student")
        facts = _facts("EDUCATION", "EXPERIENCE", "AWARD")
        candidates = StorylineCandidates(candidates=(_story(list(facts)),))
        client = _mock_client(candidates)

        for _ in range(10):
            result = propose_storylines(
                student=student, facts=facts, inputs={}, theme_kind=ThemeKind.PLAN, client=client
            )
            assert result == candidates

        call_kwargs = client.responses.parse.call_args.kwargs
        payload_text = " ".join(str(message["content"]) for message in call_kwargs["input"])
        assert "data only" in payload_text
        assert "not instructions" in payload_text

        with pytest.raises(StorylineRateLimited):
            propose_storylines(
                student=student, facts=facts, inputs={}, theme_kind=ThemeKind.PLAN, client=client
            )


def test_propose_raises_typed_error_on_no_parsed_output(agency_a, django_user_model):
    # PF-15: the brief's bare `RuntimeError` becomes StorylineProposalFailure --
    # a refusal or schema-mismatched response must not surface as a bare
    # RuntimeError, and there is no lower rung to fall back to here.
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "storyline-student-2")
        client = _mock_client(None)
        with pytest.raises(StorylineProposalFailure):
            propose_storylines(
                student=student, facts={}, inputs={}, theme_kind=ThemeKind.PLAN, client=client
            )


def test_a_gap_statement_reaches_the_storyline_prompt():
    """Owner decision 2026-10-06: a storyline is proposed from the whole
    ledger, so a gap the student accounted for can anchor a story."""
    carer = VerifiedFact(
        category=VerifiedFact.Category.TIMELINE,
        payload={
            "start_date": "2023-06-30",
            "end_date": "2023-11-01",
            "statement": "Full-time carer for a family member.",
        },
    )
    degree = VerifiedFact(
        category=VerifiedFact.Category.EDUCATION,
        payload={"degree_as_awarded": "BSc", "institution_original": "TU Munich"},
    )

    payload = _facts_payload({carer.id: carer, degree.id: degree})

    assert "Full-time carer for a family member." in payload
    assert "TIMELINE" in payload
    assert "TU Munich" in payload
