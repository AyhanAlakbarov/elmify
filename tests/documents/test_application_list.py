"""Inputs and requirement-list building for one CV generation (CV build step 4.2)."""

from uuid import uuid4

import pytest

from apps.documents import document_worker
from apps.documents.application_list import build_for, inputs_for, track_for
from apps.documents.document_queue import DocumentWorkMessage
from apps.documents.generation import GenerationResult
from apps.documents.models import DocumentDraft, VerifiedFact
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.funding.models import (
    FundingFamily,
    FundingOpportunity,
    OpportunityScope,
    ProgramStatement,
)
from apps.portals.models import Application, ApplicationLink
from apps.tenancy.context import tenant_scope
from tests.documents.conftest import make_identity_fact
from tests.funding.conftest import make_db_candidate, make_run

pytestmark = pytest.mark.django_db


def _content() -> CVContent:
    return CVContent(
        personal_information=PersonalInformation(
            full_name="Jane Doe", email="jane@example.com"
        ),
        education=(
            EducationEntry(
                degree_as_awarded="BSc",
                institution_original="Example U",
                city="Berlin",
                country="DE",
                start_date="2020-09-01",
            ),
        ),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )


def _award(*, name: str = "DAAD EPOS", **overrides) -> FundingOpportunity:
    fields = {
        "canonical_key": f"funder:{uuid4()}",
        "name": name,
        "family": FundingFamily.PRIVATE_FOUNDATION,
        "scope_type": OpportunityScope.GLOBAL,
    }
    fields.update(overrides)
    return FundingOpportunity.objects.create(**fields)


def _award_card(agency, student, *, opportunity: FundingOpportunity | None = None) -> Application:
    opp = opportunity or _award()
    run = make_run(agency, student)
    candidate = make_db_candidate(agency, run, program_name=opp.name)
    with tenant_scope(agency.id):
        candidate.opportunity = opp
        candidate.save(update_fields=["opportunity"])
        return Application.objects.create(
            tenant=agency,
            student=student,
            program_id=opp.id,
            candidate=candidate,
        )


def _programme_card(agency, student, program_factory, **prog_overrides) -> Application:
    programme = program_factory(**prog_overrides)
    with tenant_scope(agency.id):
        return Application.objects.create(
            tenant=agency,
            student=student,
            program_id=programme.id,
        )


def _run_generate(
    agency,
    student,
    monkeypatch,
    *,
    application: Application | None = None,
    programme_id=None,
) -> None:
    monkeypatch.setattr(
        document_worker,
        "generate_cv",
        lambda **_kw: GenerationResult(content=_content(), verdicts=(), retried=False),
    )
    with tenant_scope(agency.id):
        if not VerifiedFact.objects.filter(
            student=student, category=VerifiedFact.Category.IDENTITY
        ).exists():
            make_identity_fact(student)
    document_worker._generate(
        DocumentWorkMessage(
            action="generate",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency.id,
            student_id=student.id,
            application_id=application.id if application is not None else None,
            programme_id=(
                programme_id
                if programme_id is not None
                else (application.program_id if application is not None else None)
            ),
        )
    )


def test_an_award_cards_cv_records_its_scholarship(
    agency_a, membership_a, monkeypatch
) -> None:
    card = _award_card(agency_a, membership_a, opportunity=_award(name="DAAD EPOS"))
    _run_generate(agency_a, membership_a, monkeypatch, application=card)
    with tenant_scope(agency_a.id):
        draft = DocumentDraft.objects.get(application=card)
        card.refresh_from_db()
    assert draft.programme_id is None
    assert draft.funding_opportunity_id == card.candidate.opportunity_id
    assert draft.destination_label == "DAAD EPOS"
    assert card.cv_status == Application.CVStatus.MADE


def test_a_programme_cards_cv_saves_its_list_and_digest(
    agency_a, membership_a, monkeypatch, program_factory
) -> None:
    card = _programme_card(agency_a, membership_a, program_factory)
    _run_generate(agency_a, membership_a, monkeypatch, application=card)
    with tenant_scope(agency_a.id):
        draft = DocumentDraft.objects.get(application=card)
    assert draft.requirements is not None
    assert len(draft.requirements_digest) == 64
    assert draft.is_general is False


def test_a_generate_without_application_or_programme_is_the_general_cv(
    agency_a, membership_a, monkeypatch
) -> None:
    _run_generate(
        agency_a, membership_a, monkeypatch, application=None, programme_id=None
    )
    with tenant_scope(agency_a.id):
        assert DocumentDraft.objects.get(student=membership_a).is_general is True


def test_a_repeat_job_with_the_same_list_makes_no_second_draft(
    agency_a, membership_a, monkeypatch, program_factory
) -> None:
    card = _programme_card(agency_a, membership_a, program_factory)
    _run_generate(agency_a, membership_a, monkeypatch, application=card)
    _run_generate(agency_a, membership_a, monkeypatch, application=card)
    with tenant_scope(agency_a.id):
        assert DocumentDraft.objects.filter(application=card).count() == 1


def test_the_track_comes_from_research_facts_when_the_programme_states_none(
    agency_a, membership_a, program_factory
) -> None:
    from django.utils import timezone

    with tenant_scope(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.RESEARCH,
            payload={"title": "Lab thesis"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            confirmed_by=membership_a,
            confirmed_at=timezone.now(),
            created_by=membership_a,
        )
        assert (
            track_for(program_factory(academic_track=""), membership_a) == "research"
        )


def test_an_unknown_id_is_still_dropped_with_a_warning(
    agency_a, membership_a, monkeypatch, caplog
) -> None:
    with caplog.at_level("WARNING", logger="apps.documents.document_worker"):
        _run_generate(
            agency_a,
            membership_a,
            monkeypatch,
            application=None,
            programme_id=uuid4(),
        )
    assert "DocumentGenerateUnknownProgramme" in caplog.text
    with tenant_scope(agency_a.id):
        assert not DocumentDraft.objects.exists()


def test_inputs_for_collects_linked_award_and_together_routes(
    agency_a, membership_a, program_factory
) -> None:
    programme = program_factory(name="MSc Robotics")
    with_admission = _award(
        name="Faculty Waiver",
        scope_type=OpportunityScope.PROGRAM,
        program=programme,
        route="CONSIDERED_WITH_ADMISSION",
    )
    separate = _award(
        name="Chevening",
        route="SEPARATE_APPLICATION",
    )
    programme_card = _programme_card(
        agency_a, membership_a, lambda: programme
    )
    award_card = _award_card(agency_a, membership_a, opportunity=separate)
    with tenant_scope(agency_a.id):
        ApplicationLink.objects.create(
            tenant=agency_a,
            from_app=award_card,
            to_app=programme_card,
        )
        resolved = inputs_for(programme_card, programme.id)
        assert resolved is not None
        assert resolved.programme == programme
        assert resolved.opportunity == separate
        assert resolved.together == (with_admission,)
        assert resolved.destination_label == "MSc Robotics, Example University"
        from django.utils import timezone

        from apps.funding.models import OfficialSource, OfficialSourceSnapshot

        source = OfficialSource.objects.create(
            canonical_url=f"https://official.example/{uuid4()}",
            publisher="Official University",
            source_type=OfficialSource.Type.PROGRAM,
        )
        snapshot = OfficialSourceSnapshot.objects.create(
            source=source,
            s3_key=f"official-sources/{uuid4()}",
            s3_version_id="1",
            sha256="0" * 64,
            final_url=source.canonical_url,
            redirect_chain=[],
            retrieved_at=timezone.now(),
            admissions_cycle="2027",
            content_type="text/html",
            byte_size=1,
        )
        ProgramStatement.objects.create(
            program=programme,
            snapshot=snapshot,
            kind=ProgramStatement.Kind.COMPETENCY,
            requirement=ProgramStatement.Requirement.REQUIRED,
            text="Control theory and kinematics",
            label="Control theory",
        )
        built = build_for(resolved, membership_a, programme_card)
    assert any(
        item.key == "competency" and item.sentence == "Control theory and kinematics"
        for item in built.items
    )
