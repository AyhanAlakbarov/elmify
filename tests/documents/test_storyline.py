from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from apps.documents.letter_schemas import Storyline
from apps.documents.models import DocumentDraft, VerifiedFact
from apps.documents.storyline import (
    StorylineCandidates,
    StorylineProposalFailure,
    StorylineRateLimited,
    ThemeKind,
    _facts_payload,
    choose_opening_kind,
    choose_storyline,
    fitting_story_shapes,
    opening_instruction_for,
    propose_storylines,
    recent_theme_texts,
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


def test_propose_storylines_steers_micro_moments_by_reader_and_forbids_family_origin(
    agency_a, django_user_model
):
    """N-04 / N-12: each ThemeKind steers uncheckable intellectual or sectoral
    micro-moments inside real facts while forbidding family/childhood origins."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "storyline-micro-moment")
        facts = _facts("EDUCATION", "EXPERIENCE", "AWARD")
        candidates = StorylineCandidates(candidates=(_story(list(facts)),))

        for kind, expected_phrase in (
            (ThemeKind.PROBLEM, "what assumption broke, what method hit a limit"),
            (ThemeKind.PLAN, "observable sectoral or workflow bottleneck at home"),
            (ThemeKind.MATCH, "what intellectual question or methodological limit arose"),
        ):
            client = _mock_client(candidates)
            propose_storylines(
                student=student, facts=facts, inputs={}, theme_kind=kind, client=client
            )
            dev_msg = str(client.responses.parse.call_args.kwargs["input"][0]["content"])
            assert expected_phrase in dev_msg
            assert "never inventing family biography, childhood origins" in dev_msg


def test_non_latin_and_diacritic_themes_are_tokenized_for_similarity():
    """Unicode letters (Cyrillic, Turkish diacritics) must be tokenized whole so
    similarity tie-breaking works outside ASCII."""
    facts = _facts("EDUCATION", "EXPERIENCE", "AWARD")
    ids = list(facts)
    common = _story(ids, theme="разработка систем управления автономными роботами")
    rare = _story(ids, theme="Türkiye enerji şebekesinde yük tahmini")
    recent = ("разработка систем управления мобильными роботами",)
    candidates = StorylineCandidates(candidates=(common, rare))
    assert choose_storyline(candidates, facts=facts, recent_themes=recent) == rare


def test_recent_theme_texts_excludes_current_student_and_superseded_drafts(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        me = _student(agency_a, django_user_model, "story-me")
        peer = _student(agency_a, django_user_model, "story-peer")
        DocumentDraft.objects.create(
            student=me,
            kind=DocumentDraft.Kind.CORE_NARRATIVE,
            version=1,
            content={"language": "en", "units": [], "storyline": {"theme": "my own theme"}},
            status=DocumentDraft.Status.DRAFT,
        )
        DocumentDraft.objects.create(
            student=peer,
            kind=DocumentDraft.Kind.CORE_NARRATIVE,
            version=1,
            content={"language": "en", "units": [], "storyline": {"theme": "superseded peer"}},
            status=DocumentDraft.Status.SUPERSEDED,
        )
        DocumentDraft.objects.create(
            student=peer,
            kind=DocumentDraft.Kind.CORE_NARRATIVE,
            version=2,
            content={"language": "en", "units": [], "storyline": {"theme": "active peer theme"}},
            status=DocumentDraft.Status.DRAFT,
        )
        assert recent_theme_texts(student=me) == ("active peer theme",)


def test_identity_facts_never_reach_storyline_prompt_payload():
    identity = VerifiedFact(
        category=VerifiedFact.Category.IDENTITY,
        payload={"full_name": "Secret Name", "date_of_birth": "1999-04-12"},
    )
    degree = VerifiedFact(
        category=VerifiedFact.Category.EDUCATION,
        payload={"degree_as_awarded": "BSc", "institution_original": "TU Munich"},
    )
    payload = _facts_payload({identity.id: identity, degree.id: degree})
    assert "Secret Name" not in payload
    assert "1999-04-12" not in payload
    assert "IDENTITY" not in payload
    assert "TU Munich" in payload


def test_fitting_story_shapes_matches_confirmed_ledger_and_steers_prompt(
    agency_a, django_user_model
):
    facts = {
        uuid4(): _Fact("TIMELINE", {"statement": "Six-month carer leave."}),
        uuid4(): _Fact("RESEARCH", {"thesis_title": "MPC Gait", "outcomes": ["stable trotting"]}),
        uuid4(): _Fact("EXPERIENCE", {"role": "Robotics Intern"}),
    }
    shapes = fitting_story_shapes(facts, ThemeKind.PROBLEM)
    assert "setback_turned" in shapes
    assert "thesis_continued" in shapes
    assert "surprise_result" in shapes
    assert "problem_met_at_work" in shapes

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "storyline-shapes")
        candidates = StorylineCandidates(candidates=(_story(list(facts)),))
        client = _mock_client(candidates)
        propose_storylines(
            student=student, facts=facts, inputs={}, theme_kind=ThemeKind.PROBLEM, client=client
        )
        dev_msg = str(client.responses.parse.call_args.kwargs["input"][0]["content"])
        assert "Give each candidate a distinct narrative shape chosen from:" in dev_msg
        assert "setback_turned" in dev_msg
        assert "thesis_continued" in dev_msg


def test_culture_routed_opening_rotation():
    de_kinds = {
        choose_opening_kind(country_code="DE", document_language="de", seed_key=f"s:{i}")
        for i in range(40)
    }
    assert "real_moment_scene" not in de_kinds
    assert len(de_kinds) >= 4

    uk_kinds = {
        choose_opening_kind(country_code="GB", document_language="en", seed_key=f"s:{i}")
        for i in range(40)
    }
    assert "real_moment_scene" in uk_kinds
    assert "plain_status" not in uk_kinds

    instruction = opening_instruction_for(
        country_code="DE", document_language="de", seed_key=""
    )
    assert "Open the first paragraph" in instruction


def test_readings_augment_fitting_story_shapes_and_reach_propose_storylines_prompt(
    agency_a, django_user_model
):
    from apps.documents.evidence.readings import UsableBullet, UsableReading

    facts = {
        uuid4(): _Fact("EDUCATION", {"degree_as_awarded": "BSc"}),
        uuid4(): _Fact("LANGUAGE", {"language": "en", "level": "C1"}),
    }
    reading = UsableReading(
        source="upload",
        url=None,
        document_id=uuid4(),
        summary="Bachelor thesis on gait control",
        kind="thesis",
        names=("MPC Gait",),
        first_commit=None,
        last_commit=None,
        bullets=(
            UsableBullet(
                text="Derived stability bounds for model-predictive gait control.",
                evidence=("stability", "gait"),
                verdict="supported",
            ),
        ),
    )
    shapes = fitting_story_shapes(facts, ThemeKind.PROBLEM, readings=(reading,))
    assert "thesis_continued" in shapes

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "storyline-readings")
        candidates = StorylineCandidates(candidates=(_story(list(facts)),))
        client = _mock_client(candidates)
        propose_storylines(
            student=student,
            facts=facts,
            inputs={},
            theme_kind=ThemeKind.PROBLEM,
            readings=(reading,),
            client=client,
        )
        user_msg = str(client.responses.parse.call_args.kwargs["input"][1]["content"])
        assert "Checked readings (data only):" in user_msg
        assert "Derived stability bounds for model-predictive gait control." in user_msg


def test_recent_theme_texts_prioritizes_same_programme_and_recent_programme_sentences(
    agency_a, django_user_model
):
    from apps.documents.models import DocumentDraft
    from apps.documents.storyline import recent_programme_sentences, recent_theme_texts

    from .conftest import make_program

    with tenant_scope(agency_a.id):
        s1 = _student(agency_a, django_user_model, "cohort-s1")
        s2 = _student(agency_a, django_user_model, "cohort-s2")
        prog_a = make_program(country_code="DE")
        prog_b = make_program(country_code="NL")

        f1, f2 = uuid4(), uuid4()
        story_a = _story([f1, f2], theme="same-programme-theme").model_dump(mode="json")
        story_b = _story([f1, f2], theme="other-programme-theme").model_dump(mode="json")

        DocumentDraft.objects.create(
            tenant_id=agency_a.id,
            student=s1,
            programme=prog_a,
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            version=1,
            content={
                "schema_version": 1,
                "language": "en",
                "header_block": None,
                "units": [
                    {
                        "archetype": "WHY_PROGRAMME",
                        "text": (
                            "The Robotics Chair at TU Munich investigates nonlinear model "
                            "predictive control for legged locomotion."
                        ),
                        "claims": [],
                        "answers_question": None,
                    }
                ],
                "storyline": story_a,
            },
        )

        DocumentDraft.objects.create(
            tenant_id=agency_a.id,
            student=s1,
            programme=prog_b,
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            version=2,
            content={
                "schema_version": 1,
                "language": "en",
                "header_block": None,
                "units": [],
                "storyline": story_b,
            },
        )

        themes = recent_theme_texts(programme_id=prog_a.id, limit=2)
        assert themes[0] == "same-programme-theme"
        assert "other-programme-theme" in themes

        cohort = recent_programme_sentences(programme_id=prog_a.id, student=s2)
        assert (
            "the robotics chair at tu munich investigates nonlinear model predictive "
            "control for legged locomotion."
        ) in cohort
        assert recent_programme_sentences(programme_id=prog_a.id, student=s1) == frozenset()






