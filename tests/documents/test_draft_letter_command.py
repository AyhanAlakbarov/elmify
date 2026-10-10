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
