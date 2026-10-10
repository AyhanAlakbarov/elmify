from unittest.mock import patch

import pytest

from apps.documents.letter_revisions import (
    AdviceRequired,
    add_student_stated_fact,
    request_letter_factual_correction,
    request_letter_style_revision,
)
from apps.documents.models import DocumentDraft, RevisionRequest, VerifiedFact
from apps.documents.revisions import RevisionRejected
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _draft(agency, django_user_model, name, kind=DocumentDraft.Kind.MOTIVATION_LETTER):
    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    content = CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
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
    draft = DocumentDraft.objects.create(
        student=student,
        kind=kind,
        version=1,
        content=content.model_dump(mode="json"),
        status=DocumentDraft.Status.DRAFT,
    )
    return student, draft


def test_style_revision_with_no_advice_applies_immediately(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, draft = _draft(agency_a, django_user_model, "lr1")
        request = request_letter_style_revision(
            document=draft, requested_by=student, note="tighten the opening"
        )
        assert request.advice_shown == ""


def test_style_revision_with_advice_blocks_until_acknowledged(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, draft = _draft(agency_a, django_user_model, "lr2")
        with pytest.raises(AdviceRequired) as excinfo:
            request_letter_style_revision(
                document=draft,
                requested_by=student,
                note="cut the curriculum-fit paragraph",
                advice_text=(
                    "TUM scores the letter on curriculum fit; cutting this removes the "
                    "only paragraph that does that."
                ),
                rule_id="L-050",
            )
        assert "curriculum fit" in excinfo.value.advice_text


def test_style_revision_applies_after_acknowledgement_and_records_advice(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student, draft = _draft(agency_a, django_user_model, "lr3")
        request = request_letter_style_revision(
            document=draft,
            requested_by=student,
            note="cut the curriculum-fit paragraph",
            advice_text="TUM scores the letter on curriculum fit.",
            rule_id="L-050",
            acknowledge_advice=True,
        )
        assert request.advice_shown == "TUM scores the letter on curriculum fit."


def test_style_revision_uncapped_for_motivation_letter(agency_a, django_user_model):
    """PF-17 / spec decision 5: per-programme letters are uncapped -- a 3rd
    (and beyond) STYLE_STRUCTURE round on a MOTIVATION_LETTER draft must not
    raise, proving _create_style_revision's MOTIVATION_LETTER branch bypasses
    the shared 2-round cap rather than merely being untested."""
    with tenant_scope(agency_a.id):
        student, draft = _draft(agency_a, django_user_model, "lr7")
        for i in range(4):
            request = request_letter_style_revision(
                document=draft, requested_by=student, note=f"pass {i}"
            )
        assert request.advice_shown == ""


def test_style_revision_still_capped_for_core_narrative(agency_a, django_user_model):
    """The other side of PF-17: a document kind that is NOT MOTIVATION_LETTER
    (e.g. CORE_NARRATIVE) must still route through the shared request_revision
    and hit its 2-round cap on the 3rd call."""
    with tenant_scope(agency_a.id):
        student, draft = _draft(
            agency_a, django_user_model, "lr8", kind=DocumentDraft.Kind.CORE_NARRATIVE
        )
        for _ in range(2):
            request_letter_style_revision(document=draft, requested_by=student, note="tighten")
        with pytest.raises(RevisionRejected):
            request_letter_style_revision(document=draft, requested_by=student, note="one more")


def test_add_student_stated_fact_is_confirmed_immediately(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="lr4")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        fact = add_student_stated_fact(
            student=student,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={"description": "led a robotics team of five"},
            source_ref="revision-2026-08-23",
        )
        assert fact.confirmed_by_id == student.id
        assert fact.confirmed_at is not None
        assert fact.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT


def test_letter_factual_correction_writes_fact_and_revision_request_together(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student, draft = _draft(agency_a, django_user_model, "lr5")
        request = request_letter_factual_correction(
            document=draft,
            student=student,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={"description": "led a robotics team of five"},
            source_ref="revision-2026-08-23",
        )
        assert request.kind == RevisionRequest.Kind.FACTUAL_CORRECTION
        assert request.superseding_fact.confirmed_by_id == student.id
        # unlimited: a second one must not raise
        request_letter_factual_correction(
            document=draft,
            student=student,
            category=VerifiedFact.Category.AWARD,
            payload={"description": "won a hackathon"},
            source_ref="revision-2026-08-23b",
        )


def test_letter_factual_correction_rolls_back_fact_if_revision_request_fails(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student, draft = _draft(agency_a, django_user_model, "lr6")
        with patch(
            "apps.documents.letter_revisions.request_revision", side_effect=RuntimeError("boom")
        ):
            with pytest.raises(RuntimeError):
                request_letter_factual_correction(
                    document=draft,
                    student=student,
                    category=VerifiedFact.Category.EXPERIENCE,
                    payload={"description": "led a robotics team of five"},
                    source_ref="revision-2026-08-23",
                )
        assert not VerifiedFact.objects.filter(student=student).exists()
