"""The letter engine's first caller: it writes a draft and stops."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import CommandError, call_command

from apps.documents.letter_schemas import ClaimKind, LetterClaim, LetterContent, LetterUnit
from apps.documents.models import DocumentDraft
from apps.funding.models import ApplicationPrompt
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

from .conftest import make_identity_fact, make_program

pytestmark = pytest.mark.django_db


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _prompt(programme, **overrides):
    fields = dict(
        programme=programme,
        cycle="2027",
        source_url="https://example.test/apply",
        confidence=0.9,
        source=ApplicationPrompt.Source.EXTRACTED,
        funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        archetypes=["WHY_PROGRAMME"],
        questions=[],
        document_language="en",
    )
    fields.update(overrides)
    return ApplicationPrompt.objects.create(**fields)


def _content():
    claim = LetterClaim(
        text="the robotics lab",
        span_start=0,
        span_end=16,
        kind=ClaimKind.SOURCED,
        source_url="https://example.test/robotics",
    )
    return LetterContent(
        language="en",
        units=(LetterUnit(archetype="WHY_PROGRAMME", text="the robotics lab", claims=(claim,)),),
    )


def _client(content=None):
    client = MagicMock()
    response = MagicMock()
    response.output_parsed = content or _content()
    response.output = []
    client.responses.parse.return_value = response
    return client


def _run(agency, student, programme, **options):
    out = StringIO()
    with patch("apps.documents.letters.OpenAI", return_value=_client()):
        call_command(
            "draft_letter",
            tenant=str(agency.id),
            student=str(student.id),
            programme=str(programme.id),
            cycle="2027",
            stdout=out,
            **options,
        )
    return out.getvalue()


def test_it_writes_a_draft_and_approves_nothing(agency_a, django_user_model) -> None:
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft1")
        programme = make_program()
        _prompt(programme)
        output = _run(agency_a, student, programme)
        draft = DocumentDraft.objects.get(student=student)
        assert draft.kind == DocumentDraft.Kind.MOTIVATION_LETTER
        assert draft.status == DocumentDraft.Status.DRAFT
        assert draft.approved_by is None and draft.approved_at is None
        assert draft.programme_id == programme.id
        assert str(draft.id) in output
        assert "nothing is approved" in output


def test_it_says_when_the_wrong_institution_gate_checks_nothing(
    agency_a, django_user_model
) -> None:
    """Passing no --forbid leaves that gate inert, and silence would imply a
    check the command did not make."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft2")
        programme = make_program()
        _prompt(programme)
        assert "checks nothing" in _run(agency_a, student, programme)


def test_a_second_run_writes_version_two(agency_a, django_user_model) -> None:
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft3")
        programme = make_program()
        _prompt(programme)
        _run(agency_a, student, programme)
        _run(agency_a, student, programme)
        assert sorted(
            DocumentDraft.objects.filter(student=student).values_list("version", flat=True)
        ) == [1, 2]


def test_a_refusal_is_reported_and_writes_no_draft(agency_a, django_user_model) -> None:
    """A structure outside the engine is the engine working, not the command
    failing -- and a refused letter must leave nothing behind."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft4")
        programme = make_program()
        _prompt(programme, structure=ApplicationPrompt.Structure.VIDEO)
        with pytest.raises(CommandError, match="NotGeneratable"):
            _run(agency_a, student, programme)
        assert not DocumentDraft.objects.filter(student=student).exists()


def test_a_missing_prompt_names_what_to_do_about_it(agency_a, django_user_model) -> None:
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft5")
        programme = make_program()
        with pytest.raises(CommandError, match="resolve one first"):
            _run(agency_a, student, programme)


def test_render_writes_a_pdf_where_it_was_told(agency_a, django_user_model, tmp_path) -> None:
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft6")
        programme = make_program()
        _prompt(programme)
        target = tmp_path / "letter.pdf"
        output = _run(agency_a, student, programme, render=str(target))
        assert target.read_bytes().startswith(b"%PDF")
        assert str(target) in output


def test_the_head_and_foot_of_a_formal_letter_are_filled(
    agency_a, django_user_model, tmp_path
) -> None:
    """The three things only a caller knows reach `render_letter`.

    They were parameters with defaults and no filler, so a formal letter
    rendered with no addressee and no signature and nothing said so. The
    `funder_kind` is asserted too: `_shape_instructions` promises the model
    that the salutation and sign-off are added at render, and only the same
    prompt field on both sides keeps that promise true.

    `place_and_date` stays empty on purpose -- see the comment at the call
    site; nothing in the ledger holds the town the student writes from.
    """
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft7")
        make_identity_fact(student, full_name="Jane Doe")
        programme = make_program(country_code="DE")
        _prompt(programme)
        with patch(
            "apps.documents.management.commands.draft_letter.render_letter"
        ) as render:
            render.return_value = MagicMock(pdf_bytes=b"%PDF", byte_size=4, variant="LETTER_PDF")
            _run(agency_a, student, programme, render=str(tmp_path / "letter.pdf"))
    kwargs = render.call_args.kwargs
    assert kwargs["funder_kind"] == ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION
    assert kwargs["addressee"] == "Stub University\nStub City, DE"
    assert kwargs["applicant_name"] == "Jane Doe"
    assert "place_and_date" not in kwargs


def test_a_later_passport_identity_row_does_not_blank_the_signature(
    agency_a, django_user_model, tmp_path
) -> None:
    from django.utils import timezone

    from apps.documents.models import VerifiedFact

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft8")
        make_identity_fact(student, full_name="Jane Doe")
        VerifiedFact.objects.create(
            student=student, category=VerifiedFact.Category.IDENTITY,
            payload={"date_of_birth": "1999-04-12"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:test", confirmed_by=student,
            confirmed_at=timezone.now(), created_by=student,
        )
        programme = make_program(country_code="DE")
        _prompt(programme)
        with patch(
            "apps.documents.management.commands.draft_letter.render_letter"
        ) as render:
            render.return_value = MagicMock(pdf_bytes=b"%PDF", byte_size=4, variant="LETTER_PDF")
            _run(agency_a, student, programme, render=str(tmp_path / "letter.pdf"))
    assert render.call_args.kwargs["applicant_name"] == "Jane Doe"


def _blocked(programme) -> None:
    from apps.funding.models import Program
    from tests.research.provenance_helpers import make_body, recognise

    Program.objects.filter(id=programme.id).update(
        evidence_domain="bircham.edu", evidence_institutional=True
    )
    recognise(make_body("bircham.edu"), "bircham.edu", "mill_list")


def test_a_blocked_programme_gets_no_letter(agency_a, django_user_model) -> None:
    """Spec §7.5: operator commands print the verdict and refuse BLOCKED."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft-blocked")
        programme = make_program()
        _prompt(programme)
        _blocked(programme)
        with pytest.raises(CommandError, match=r"BLOCKED \(mill_list\)"):
            _run(agency_a, student, programme)
        assert not DocumentDraft.objects.filter(student=student).exists()


def test_the_verdict_is_printed(agency_a, django_user_model) -> None:
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft-verdict")
        programme = make_program()
        _prompt(programme)
        assert "provenance: UNCONFIRMED (evidence_off_domain)" in _run(agency_a, student, programme)


def test_draft_letter_forwards_usable_readings_into_generate_letter(
    agency_a, django_user_model
) -> None:
    from apps.documents.evidence.readings import UsableBullet, UsableReading

    sample = (
        UsableReading(
            source="upload",
            url=None,
            document_id=None,
            summary="Bachelor thesis on demand modelling.",
            kind="thesis",
            names=("Jane Doe",),
            first_commit=None,
            last_commit=None,
            bullets=(
                UsableBullet(
                    text="Built a stochastic demand model.",
                    evidence=("stochastic demand",),
                    verdict="supported",
                ),
            ),
        ),
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft-readings")
        programme = make_program()
        _prompt(programme)
        with (
            patch(
                "apps.documents.management.commands.draft_letter.usable_readings",
                return_value=sample,
            ),
            patch(
                "apps.documents.management.commands.draft_letter.generate_letter"
            ) as gen_mock,
        ):
            gen_mock.return_value = MagicMock(
                content=_content(),
                retried=False,
                claim_verdicts=(),
                gate_violations=(),
            )
            call_command(
                "draft_letter",
                tenant=str(agency_a.id),
                student=str(student.id),
                programme=str(programme.id),
                cycle="2027",
                stdout=StringIO(),
            )
    assert gen_mock.call_args.kwargs["readings"] == sample


def test_draft_letter_plans_storyline_and_discovers_research_fit_when_facts_exist(
    agency_a, django_user_model
) -> None:
    from django.utils import timezone

    from apps.documents.letter_schemas import Storyline
    from apps.documents.models import NarrativeInput, VerifiedFact
    from apps.documents.research_fit.service import ResearchFitOutcome
    from apps.documents.storyline import StorylineCandidates

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft-full-pipeline")
        programme = make_program(country_code="DE")
        _prompt(programme)
        now = timezone.now()
        f1 = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"degree_as_awarded": "BSc Computer Science"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="doc:1",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        f2 = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.RESEARCH,
            payload={"title": "Distributed Consensus under Packet Loss"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="doc:2",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        f3 = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={"role": "Systems Intern"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="doc:3",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        chosen = Storyline(
            theme="from empirical packet-loss failure to formal consensus verification",
            theme_kind="MATCH",
            anchors=(f1.id, f2.id, f3.id),
            turn=f2.id,
            gap="formal model checking for asynchronous networks",
            assumptions=("because the simulation could not bound worst-case latency",),
            future="build verified distributed storage systems",
        )
        fit_row = NarrativeInput.objects.create(
            student=student,
            kind=NarrativeInput.Kind.RESEARCH_FIT,
            text="The Chair of Distributed Systems teaches formal protocol verification.",
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
            confirmed_at=now,
            provenance={
                "program_id": str(programme.id),
                "sentence": (
                    "The Chair of Distributed Systems teaches formal protocol verification."
                ),
                "entity": "Chair of Distributed Systems",
                "source_url": "https://tum.de/distributed",
                "page_digest": "a" * 64,
                "kind": "research_group",
                "rung": 1,
                "anchor_fact_id": str(f2.id),
                "judgement": "strong",
                "topic_hash": "h",
                "cost_usd": 0.0,
                "provider": "exa",
            },
        )
        # Hide fit_row from the initial DB load so _ensure_research_fit has to run
        # propose_research_fit and merge fit_row into inputs.
        initial_inputs = list(NarrativeInput.objects.none())
        with (
            patch(
                "apps.documents.management.commands.draft_letter.NarrativeInput.objects.filter",
                return_value=initial_inputs,
            ),
            patch(
                "apps.documents.management.commands.draft_letter.propose_storylines",
                return_value=StorylineCandidates(candidates=(chosen,)),
            ) as prop_story,
            patch(
                "apps.documents.management.commands.draft_letter.propose_research_fit",
                return_value=ResearchFitOutcome(
                    status="matched",
                    rung=1,
                    narrative_input=fit_row,
                    cost_usd=0.0,
                    model_calls=2,
                ),
            ) as prop_fit,
            patch(
                "apps.documents.management.commands.draft_letter.generate_letter",
            ) as gen_mock,
        ):
            gen_mock.return_value = MagicMock(
                content=_content(),
                retried=False,
                claim_verdicts=(),
                gate_violations=(),
            )
            call_command(
                "draft_letter",
                tenant=str(agency_a.id),
                student=str(student.id),
                programme=str(programme.id),
                cycle="2027",
                stdout=StringIO(),
            )
        assert prop_story.called
        assert prop_fit.called
        assert prop_fit.call_args.kwargs["storyline"] == chosen
        assert gen_mock.call_args.kwargs["storyline"] == chosen
        assert fit_row.id in gen_mock.call_args.kwargs["inputs"]


def test_draft_letter_logs_and_continues_when_storyline_proposal_fails(
    agency_a, django_user_model
) -> None:
    from django.utils import timezone

    from apps.documents.models import VerifiedFact
    from apps.documents.research_fit.service import ResearchFitOutcome
    from apps.documents.storyline import StorylineProposalFailure

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft-degraded-storyline")
        programme = make_program(country_code="DE")
        _prompt(programme)
        now = timezone.now()
        for idx, cat in enumerate(
            (
                VerifiedFact.Category.EDUCATION,
                VerifiedFact.Category.RESEARCH,
                VerifiedFact.Category.EXPERIENCE,
            )
        ):
            VerifiedFact.objects.create(
                student=student,
                category=cat,
                payload={"title": f"fact-{idx}"},
                source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
                source_ref=f"doc:{idx}",
                confirmed_by=student,
                confirmed_at=now,
                created_by=student,
            )
        out = StringIO()
        with (
            patch(
                "apps.documents.management.commands.draft_letter.propose_storylines",
                side_effect=StorylineProposalFailure("upstream timeout"),
            ),
            patch(
                "apps.documents.management.commands.draft_letter.propose_research_fit",
                return_value=ResearchFitOutcome(
                    status="no_match", rung=None, narrative_input=None, cost_usd=0.0, model_calls=0
                ),
            ),
            patch(
                "apps.documents.management.commands.draft_letter.generate_letter",
            ) as gen_mock,
        ):
            gen_mock.return_value = MagicMock(
                content=_content(),
                retried=False,
                claim_verdicts=(),
                gate_violations=(),
            )
            call_command(
                "draft_letter",
                tenant=str(agency_a.id),
                student=str(student.id),
                programme=str(programme.id),
                cycle="2027",
                stdout=out,
            )
        assert "storyline skipped (StorylineProposalFailure): upstream timeout" in out.getvalue()
        assert gen_mock.call_args.kwargs["storyline"] is None


def test_other_draft_programmes_auto_populate_forbidden_institution_names(
    agency_a, django_user_model
) -> None:
    from apps.documents.models import DocumentDraft
    from apps.documents.research_fit.service import ResearchFitOutcome

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "draft-auto-forbid")
        target_prog = make_program(country_code="DE")
        target_prog.institution.name = "TU Munich"
        target_prog.institution.save(update_fields=["name"])
        other_prog = make_program(country_code="CH")
        other_prog.institution.name = "ETH Zurich"
        other_prog.institution.save(update_fields=["name"])
        _prompt(target_prog)
        DocumentDraft.objects.create(
            student=student,
            programme=other_prog,
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            version=1,
            content={},
        )
        out = StringIO()
        with (
            patch(
                "apps.documents.management.commands.draft_letter.propose_research_fit",
                return_value=ResearchFitOutcome(
                    status="no_match", rung=None, narrative_input=None, cost_usd=0.0, model_calls=0
                ),
            ),
            patch(
                "apps.documents.management.commands.draft_letter.generate_letter",
            ) as gen_mock,
        ):
            gen_mock.return_value = MagicMock(
                content=_content(),
                retried=False,
                claim_verdicts=(),
                gate_violations=(),
            )
            call_command(
                "draft_letter",
                tenant=str(agency_a.id),
                student=str(student.id),
                programme=str(target_prog.id),
                cycle="2027",
                stdout=out,
            )
        forbidden = gen_mock.call_args.kwargs["forbidden_institution_names"]
        assert "ETH Zurich" in forbidden
        assert "TU Munich" not in forbidden


