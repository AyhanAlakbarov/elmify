from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.documents.generation import (
    _CV_GENERATION_RATE_LIMIT,
    ApplicationEmailMissing,
    GenerationFailure,
    GenerationRateLimited,
    GenerationRefused,
    GenerationSchemaError,
    IdentityNotConfirmed,
    generate_cv,
)
from apps.documents.models import VerifiedFact
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.documents.verification import Verdict, fact_payload
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

_EDUCATION = EducationEntry(
    degree_as_awarded="BSc",
    institution_original="Example University",
    city="Berlin",
    country="DE",
    start_date="2020-09-01",
)


def _content(summary=None):
    return CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
        education=(_EDUCATION,),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        summary=summary,
        document_language="en",
    )


def _mock_client(content=None):
    client = MagicMock()
    response = MagicMock()
    response.output_parsed = content if content is not None else _content()
    response.output = []
    response.usage = None
    response.id = "resp_1"
    client.responses.parse.return_value = response
    return client


def _student(agency, django_user_model, name, *, identity_confirmed=True):
    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency,
        user=user,
        role=Membership.Role.STUDENT,
        active=True,
        application_email=f"{name}@applications.example",
    )
    _identity_fact(student, confirmed=identity_confirmed)
    return student


def _identity_fact(student, *, confirmed=True, full_name="Jane Doe"):
    """personal_information is a verified claim now, so every generation test
    needs a fact backing the name _content() produces. Without one every
    verdict set contains an UNSUPPORTED and every first pass retries."""
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.IDENTITY,
        payload={"full_name": full_name},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="upload:test",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
        created_by=student,
    )


def _fact(student, *, confirmed, **payload_overrides):
    """Build the fact as it should be -- VerifiedFact is never edited in place."""
    payload = fact_payload(_EDUCATION, category=VerifiedFact.Category.EDUCATION)
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.EDUCATION,
        payload={**payload, **payload_overrides},
        source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        source_ref="transcript-1",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
        created_by=student,
    )


def _prompt_text(client):
    return "".join(
        str(message["content"])
        for call in client.responses.parse.call_args_list
        for message in call.kwargs["input"]
    )


def test_generate_cv_returns_content_and_verdicts(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g1")
        _fact(student, confirmed=True)
        result = generate_cv(student=student, client=_mock_client())
        assert isinstance(result.content, CVContent)
        assert result.verdicts and result.verdicts[0].verdict == Verdict.SUPPORTED


def test_unconfirmed_facts_never_reach_the_prompt(agency_a, django_user_model):
    """Spec testing item 13: unconfirmed facts are invisible to generation."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g2")
        _fact(student, confirmed=False)
        client = _mock_client()
        generate_cv(student=student, client=client)
        assert "Example University" not in _prompt_text(client)


def test_a_claim_matching_an_unconfirmed_fact_reads_uncertain(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        # Identity stays confirmed: the gate refuses to generate without it,
        # so it can no longer double as a second unconfirmed claim. The
        # education fact is the one under test.
        student = _student(agency_a, django_user_model, "g3")
        _fact(student, confirmed=False)
        result = generate_cv(student=student, client=_mock_client())
        education = [v for v in result.verdicts if v.claim_path.startswith("education")]
        assert education and all(v.verdict == Verdict.UNCERTAIN for v in education)


def test_superseded_facts_never_reach_the_prompt(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g4")
        old = _fact(student, confirmed=True)
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={**old.payload, "institution_original": "Corrected University"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="transcript-2",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            supersedes=old,
            created_by=student,
        )
        client = _mock_client()
        generate_cv(student=student, client=client)
        prompt = _prompt_text(client)
        assert "Corrected University" in prompt
        assert "Example University" not in prompt


def test_generate_cv_retries_exactly_once_on_unsupported(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g5")
        client = _mock_client()  # no facts at all -> every claim UNSUPPORTED
        result = generate_cv(student=student, client=client)
        assert result.retried is True
        assert client.responses.parse.call_count == 2


def test_generate_cv_retries_on_conflicting_too(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g6")
        _fact(student, confirmed=True, start_date="1999-01-01")
        client = _mock_client()
        result = generate_cv(student=student, client=client)
        assert result.retried is True
        assert client.responses.parse.call_count == 2


def test_generate_cv_does_not_retry_when_first_pass_clean(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g7")
        _fact(student, confirmed=True)
        client = _mock_client()
        result = generate_cv(student=student, client=client)
        assert result.retried is False
        assert client.responses.parse.call_count == 1


def test_generate_cv_rate_limited(agency_a, django_user_model):
    from apps.documents import generation

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g8")
        _fact(student, confirmed=True)
        client = _mock_client()
        for _ in range(generation._CV_GENERATION_RATE_LIMIT):
            generate_cv(student=student, client=client)
        with pytest.raises(GenerationRateLimited):
            generate_cv(student=student, client=client)


def test_generate_cv_prompt_instructs_summary_left_null_without_personal_fact(
    agency_a, django_user_model
):
    """Summary is a verified, blocking surface (Task 4): the prompt must tell
    the model to leave it null unless it can be built from a confirmed
    PERSONAL fact, or every generated CV blocks on a summary the student
    never asked for."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g9")
        _fact(student, confirmed=True)
        client = _mock_client()
        generate_cv(student=student, client=client)
        assert (
            "leave summary as null unless it can be built entirely from a confirmed "
            "personal-information fact in data"
        ) in _prompt_text(client).lower()


def test_generate_cv_populated_summary_without_personal_fact_is_unsupported(
    agency_a, django_user_model
):
    """Proves the gate actually catches it when the model ignores the
    instruction above: a populated summary with no matching confirmed
    PERSONAL fact must come back a blocking UNSUPPORTED verdict, not be
    silently accepted."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g10")
        _fact(student, confirmed=True)
        client = _mock_client(_content(summary="An accomplished, driven candidate."))
        result = generate_cv(student=student, client=client)
        summary_verdicts = [v for v in result.verdicts if v.claim_path == "summary[0]"]
        assert summary_verdicts and summary_verdicts[0].verdict == Verdict.UNSUPPORTED


def test_generate_cv_wraps_sdk_call_failures(agency_a, django_user_model):
    """The SDK's own error surface must not escape this module as-is --
    mirrors apps.research.extraction.extract_claims wrapping parser.parse
    failures in a domain exception."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g11")
        _fact(student, confirmed=True)
        client = MagicMock()
        client.responses.parse.side_effect = RuntimeError("connection reset")
        with pytest.raises(GenerationFailure) as excinfo:
            generate_cv(student=student, client=client)
        assert isinstance(excinfo.value.__cause__, RuntimeError)


def test_generate_cv_raises_refused_on_refusal(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g12")
        _fact(student, confirmed=True)
        client = MagicMock()
        response = MagicMock()
        response.output_parsed = None
        response.output = [MagicMock(type="refusal", refusal="policy")]
        client.responses.parse.return_value = response
        with pytest.raises(GenerationRefused):
            generate_cv(student=student, client=client)


def test_generate_cv_raises_schema_error_on_missing_output(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g13")
        _fact(student, confirmed=True)
        client = MagicMock()
        response = MagicMock()
        response.output_parsed = None
        response.output = []
        client.responses.parse.return_value = response
        with pytest.raises(GenerationSchemaError):
            generate_cv(student=student, client=client)


def test_generate_cv_raises_schema_error_on_invalid_parsed_output(agency_a, django_user_model):
    """output_parsed is set but doesn't validate as CVContent (e.g. the SDK
    handed back a bare dict missing required fields) -- must not leak the
    pydantic ValidationError (which embeds the offending model output) past
    this module."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g14")
        _fact(student, confirmed=True)
        client = MagicMock()
        response = MagicMock()
        response.output_parsed = {"not": "a valid CVContent"}
        response.output = []
        client.responses.parse.return_value = response
        with pytest.raises(GenerationSchemaError) as excinfo:
            generate_cv(student=student, client=client)
        assert excinfo.value.__cause__ is None


def test_generation_refuses_without_a_confirmed_identity(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "gate1", identity_confirmed=False)
        client = _mock_client()
        with pytest.raises(IdentityNotConfirmed):
            generate_cv(student=student, client=client)
        assert client.responses.parse.call_count == 0


def test_generation_refuses_without_an_application_email(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "gate2")
        student.application_email = ""
        student.save(update_fields=["application_email"])
        client = _mock_client()
        with pytest.raises(ApplicationEmailMissing):
            generate_cv(student=student, client=client)
        assert client.responses.parse.call_count == 0


def test_the_gate_runs_before_the_rate_limiter(agency_a, django_user_model):
    """Pins the ordering. rate_limited() increments a fixed-window counter, so
    checking preconditions second would burn tokens on a student for a state
    that waiting cannot fix. Reordering two lines must break something."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "gate3", identity_confirmed=False)
        for _ in range(_CV_GENERATION_RATE_LIMIT + 5):
            with pytest.raises(IdentityNotConfirmed):
                generate_cv(student=student, client=_mock_client())
        # The window was never consumed, so confirming identity is enough.
        _identity_fact(student, confirmed=True)
        result = generate_cv(student=student, client=_mock_client())
        assert isinstance(result.content, CVContent)


def test_gate_messages_carry_no_document_content(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "gate4", identity_confirmed=False)
        with pytest.raises(IdentityNotConfirmed) as caught:
            generate_cv(student=student, client=_mock_client())
        assert "Jane Doe" not in str(caught.value)
        assert "applications.example" not in str(caught.value)


def _content_with_email(email, full_name="Jane Doe"):
    base = _content()
    personal = base.personal_information.model_copy(
        update={"email": email, "full_name": full_name}
    )
    return base.model_copy(update={"personal_information": personal})


def test_email_is_stamped_on_a_clean_first_pass(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp1")
        _fact(student, confirmed=True)
        client = _mock_client(_content_with_email("hallucinated@example.com"))
        result = generate_cv(student=student, client=client)
        assert result.content.personal_information.email == student.application_email


def test_email_is_stamped_after_a_retry(agency_a, django_user_model):
    """Pins the second return path. generate_cv returns in two places -- a
    clean first pass and a post-retry return -- and stamping at one of them
    is the bug that ships."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp2")
        # No education fact, so the education claim reads UNSUPPORTED, blocks,
        # and forces the retry.
        client = _mock_client(_content_with_email("hallucinated@example.com"))
        result = generate_cv(student=student, client=client)
        assert result.retried is True
        assert result.content.personal_information.email == student.application_email


def test_full_name_is_never_stamped(agency_a, django_user_model):
    """The name is not corrected into agreement. Stamping it would manufacture
    a clean verdict for a value nobody checked -- the opposite of what the
    verifier is for. A wrong name must survive as an UNSUPPORTED verdict."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stamp3")
        _fact(student, confirmed=True)
        client = _mock_client(_content_with_email("x@example.com", full_name="Someone Else"))
        result = generate_cv(student=student, client=client)
        assert result.content.personal_information.full_name == "Someone Else"
        identity = [v for v in result.verdicts if v.claim_path == "personal_information[0]"]
        assert identity and identity[0].verdict == Verdict.UNSUPPORTED


def test_generation_prompt_forbids_inferring_sub_skills(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "gen-grid")
        _fact(student, confirmed=True)
        client = _mock_client()
        generate_cv(student=student, client=client)
        prompt = _prompt_text(client)
    assert "listening" in prompt.lower()
    assert "leave them null" in prompt.lower()


def test_the_cv_prints_the_students_own_address_when_they_have_one(
    agency_a, django_user_model
):
    """An academic CV mailed to a supervisor carries an address that is itself
    a credential. A portal is still registered with application_email."""
    from apps.documents.generation import contact_email

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "email1")
        assert contact_email(student) == "email1@applications.example"
        student.academic_email = "jane@etu.unistra.example"
        student.save(update_fields=["academic_email"])
        assert contact_email(student) == "jane@etu.unistra.example"

        client = _mock_client()
        result = generate_cv(student=student, client=client)
        assert result.content.personal_information.email == "jane@etu.unistra.example"
        assert "jane@etu.unistra.example" in _prompt_text(client)


def _pooled(name, category="SKILL"):
    from uuid import uuid4

    from apps.documents.tailoring import PooledFact

    return PooledFact(fact_id=uuid4(), category=category, name=name, kind="", evidence="")


def _tailored(*names):
    from apps.documents.tailoring import TailoredSkills

    return TailoredSkills(
        printed=tuple(_pooled(name) for name in names), gaps=("Docker",), basis="test"
    )


def _content_with_skills(*names):
    from apps.documents.schemas import SkillEntry

    return _content().model_copy(
        update={"skills": tuple(SkillEntry(name=name) for name in names)}
    )


def test_tailoring_orders_the_skills_the_programme_asked_for_and_drops_the_rest():
    from apps.documents.generation import _apply_tailoring

    content = _content_with_skills("Python", "Curling", "RDKit")
    tailored = _apply_tailoring(content, _tailored("RDKit", "Python"))
    assert [skill.name for skill in tailored.skills] == ["RDKit", "Python"]


def test_tailoring_keeps_the_untailored_list_when_it_would_empty_the_section():
    """tailor_skills excludes an unmatched model-read skill on purpose, so an
    intersection can legitimately be empty -- and a CV with no Skills section
    at all is not what that exclusion is for."""
    from apps.documents.generation import _apply_tailoring

    content = _content_with_skills("Python", "RDKit")
    assert _apply_tailoring(content, _tailored("Kubernetes")).skills == content.skills
    assert _apply_tailoring(content, None).skills == content.skills


def test_an_unprofiled_programme_leaves_the_cv_exactly_as_it_was(
    agency_a, django_user_model
):
    """No competencies on file means no match to make, not an empty CV -- and
    no model call to pay for either."""
    from apps.funding.models import Institution, Program

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "tail1")
        _fact(student, confirmed=True)
        institution = Institution.objects.create(
            canonical_key="de:example university",
            name="Example University",
            country_code="DE",
            official_website="https://university.example.test",
        )
        programme = Program.objects.create(
            institution=institution,
            canonical_key="prog:unprofiled",
            name="MSc Test",
            campus_name="Main",
            city="Town",
            country_code="DE",
            location_key="de:town",
            degree_level="MASTER",
            teaching_languages=["English"],
            duration_months=12,
        )
        # Backed by a confirmed fact, or the skill reads UNSUPPORTED and the
        # retry makes the call count say nothing about tailoring.
        from apps.documents.schemas import SkillEntry

        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.SKILL,
            payload=fact_payload(SkillEntry(name="Python"), category=VerifiedFact.Category.SKILL),
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        client = _mock_client(_content_with_skills("Python"))
        result = generate_cv(student=student, client=client, programme=programme)
        assert [skill.name for skill in result.content.skills] == ["Python"]
        assert result.gaps == ()
        # One call: the generation itself. No competencies, no match call.
        assert client.responses.parse.call_count == 1


def test_an_include_directive_names_the_field_in_the_generation_prompt(
    agency_a, django_user_model, program_factory
):
    programme = program_factory(cv_directives=[{
        "action": "include", "target": "education.ects_credits", "value": None,
        "rule_text": "State your ECTS credits.", "source_url": "",
    }])
    client = _mock_client()
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "include-student")
        generate_cv(student=student, client=client, programme=programme)
    developer = client.responses.parse.call_args.kwargs["input"][0]["content"]
    assert "education.ects_credits" in developer
    assert "State your ECTS credits." not in developer  # the sentence never enters the prompt


def test_generate_cv_prompt_carries_the_project_through_unfolded(agency_a, django_user_model):
    """The ledger now carries the project beside the title (S-037); a
    regeneration that folded it back into the title would reprint the
    ", Project Title:" header the field exists to remove."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g11")
        _fact(student, confirmed=True)
        client = _mock_client()
        generate_cv(student=student, client=client)
        assert "the project is never folded into it" in _prompt_text(client).lower()


def test_generate_cv_stamps_bullets_and_skill_category_from_confirmed_facts(
    agency_a, django_user_model
):
    from apps.documents.schemas import ExperienceEntry, SkillEntry

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g12")
        _fact(student, confirmed=True)
        exp_fact = ExperienceEntry(
            employer="EPFL",
            title="Research Intern",
            start_date="2025-09-01",
            end_date="2025-12-01",
            bullets=("Built catalyst pipeline.", "Published benchmark dataset."),
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EXPERIENCE,
            payload=fact_payload(exp_fact, category=VerifiedFact.Category.EXPERIENCE),
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        skill_fact = SkillEntry(name="Python", category="Programming")
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.SKILL,
            payload=fact_payload(skill_fact, category=VerifiedFact.Category.SKILL),
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        # Model output mutates bullets and drops skill category:
        drifted = _content().model_copy(
            update={
                "experience": (
                    exp_fact.model_copy(update={"bullets": ("Invented bullet.",)}),
                ),
                "skills": (SkillEntry(name="Python", category="Other"),),
            }
        )
        client = _mock_client(drifted)
        result = generate_cv(student=student, client=client)
        assert result.content.experience[0].bullets == exp_fact.bullets
        assert result.content.skills[0].category == "Programming"


def test_generate_cv_stamps_relevant_coursework_from_checked_transcript_courses(
    agency_a, django_user_model
):
    from apps.documents.requirement_list import Requirement, RequirementList

    req_list = RequirementList(
        items=(
            Requirement(
                document="cv",
                key="include",
                value="education.relevant_coursework",
                origin="programme",
                force="strict",
                sentence="Include relevant coursework.",
                source_url="https://uni.example/cv",
            ),
        )
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g13")
        _fact(
            student,
            confirmed=True,
            courses=[
                {"title": "Machine Learning", "credits": 6.0},
                {"title": "Quantum Chemistry", "credits": 5.0},
            ],
        )
        client = _mock_client()
        result = generate_cv(student=student, client=client, requirements=req_list)
        assert (
            result.content.education[0].relevant_coursework
            == "Machine Learning, Quantum Chemistry"
        )


def test_generate_cv_applies_ban_rules_from_requirements(agency_a, django_user_model):
    from apps.documents.constraints import ConstraintRule, Enforcement
    from apps.documents.requirement_list import Requirement, RequirementList

    ban = ConstraintRule(
        rule_id="R-PHOTO",
        key="prohibited_content",
        value=["photo", "date_of_birth"],
        enforcement=Enforcement.BINDING,
        rule_text="No photo or date of birth.",
    )
    req_list = RequirementList(
        items=(
            Requirement(
                document="cv",
                key="prohibited_content",
                value=["photo", "date_of_birth"],
                origin="scholarship",
                force="strict",
                rule=ban,
            ),
        )
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g14")
        VerifiedFact.objects.filter(
            student=student, category=VerifiedFact.Category.IDENTITY
        ).delete()
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.IDENTITY,
            payload={
                "full_name": "Jane Doe",
                "date_of_birth": "2001-04-10",
                "photo_url": "https://example.org/p.jpg",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        _fact(student, confirmed=True)
        with_banned = _content().model_copy(
            update={
                "personal_information": PersonalInformation(
                    full_name="Jane Doe",
                    email="g14@applications.example",
                    date_of_birth="2001-04-10",
                    photo_url="https://example.org/p.jpg",
                )
            }
        )
        client = _mock_client(with_banned)
        result = generate_cv(student=student, client=client, requirements=req_list)
        assert result.content.personal_information.photo_url is None
        assert result.content.personal_information.date_of_birth is None


def test_retry_preserves_clean_sections_when_second_pass_breaks_them(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g15")
        _fact(student, confirmed=True)
        # Pass 1 has clean education, but an unsupported summary -> triggers retry.
        pass1 = _content(summary="Hallucinated summary.")
        # Pass 2 removes summary, but hallucinates an unsupported institution on education.
        bad_edu = _EDUCATION.model_copy(
            update={"institution_original": "Hallucinated University"}
        )
        pass2 = _content(summary=None).model_copy(update={"education": (bad_edu,)})

        client = MagicMock()
        r1 = MagicMock(output_parsed=pass1, output=[], usage=None, id="r1")
        r2 = MagicMock(output_parsed=pass2, output=[], usage=None, id="r2")
        client.responses.parse.side_effect = [r1, r2]

        result = generate_cv(student=student, client=client)
        assert result.retried is True
        assert result.content.summary is None
        assert (
            result.content.education[0].institution_original
            == "Example University"
        )
        assert all(v.verdict == Verdict.SUPPORTED for v in result.verdicts)


def _pending_change(student):
    old = _fact(student, confirmed=True)
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.EDUCATION,
        payload={**old.payload, "city": "Hamburg"},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="upload:second",
        supersedes=old,
        created_by=student,
    )


def test_generation_refuses_while_a_newer_cv_awaits_confirmation(
    agency_a, django_user_model
):
    from apps.documents.generation import ChangesPending

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g-pending")
        _pending_change(student)
        client = _mock_client()
        with pytest.raises(ChangesPending):
            generate_cv(student=student, client=client)
    client.responses.parse.assert_not_called()


def test_the_pending_check_runs_before_the_identity_check(
    agency_a, django_user_model
):
    """A re-spelled name is itself a pending change; the student must be told
    to settle the list, not that they have no name."""
    from apps.documents.generation import ChangesPending

    with tenant_scope(agency_a.id):
        student = _student(
            agency_a, django_user_model, "g-order", identity_confirmed=True
        )
        identity = VerifiedFact.objects.get(student=student)
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Jane Q. Doe"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:second",
            supersedes=identity,
            created_by=student,
        )
        with pytest.raises(ChangesPending):
            generate_cv(student=student, client=_mock_client())


def test_generation_restores_the_ledgers_bullets(agency_a, django_user_model):
    from datetime import date as _date

    from apps.documents.schemas import ExperienceEntry

    post = ExperienceEntry(
        employer="EPFL",
        title="Research Intern",
        start_date=_date(2025, 6, 1),
        bullets=("Wrote the pipeline.",),
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g-stamp")
        _fact(student, confirmed=True)
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EXPERIENCE,
            payload=fact_payload(post, category=VerifiedFact.Category.EXPERIENCE),
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        reworded = _content().model_copy(
            update={
                "experience": (
                    post.model_copy(update={"bullets": ("Spearheaded a pipeline.",)}),
                )
            }
        )
        result = generate_cv(student=student, client=_mock_client(reworded))
    assert result.content.experience[0].bullets == ("Wrote the pipeline.",)


def test_generation_leaves_a_soft_skill_out_and_records_it(agency_a, django_user_model):
    from apps.documents.schemas import SkillEntry

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g-soft")
        _fact(student, confirmed=True)
        for name in ("Python", "Teamwork"):
            VerifiedFact.objects.create(
                student=student,
                category=VerifiedFact.Category.SKILL,
                payload={"name": name},
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref="upload:test",
                confirmed_by=student,
                confirmed_at=timezone.now(),
                created_by=student,
            )
        content = _content().model_copy(
            update={"skills": (SkillEntry(name="Python"), SkillEntry(name="Teamwork"))}
        )
        result = generate_cv(student=student, client=_mock_client(content))
    assert [s.name for s in result.content.skills] == ["Python"]
    assert [f.original for f in result.applied_fixes] == ["Teamwork"]


def test_an_omitted_soft_skill_stays_omitted_through_tailoring():
    """Fixes run before _apply_tailoring, whose empty-intersection fallback
    returns the content it was given -- already without the soft skill."""
    from apps.documents.generation import _apply_tailoring

    kept = _content_with_skills("Python")
    assert [s.name for s in _apply_tailoring(kept, _tailored("Teamwork")).skills] == ["Python"]


def test_generation_records_a_verb_fix(agency_a, django_user_model, settings):
    from datetime import date as _date

    from apps.documents.schemas import ExperienceEntry
    from apps.research.decisions import Answer

    settings.CV_VERB_JEV_ENABLED = True
    settings.DECISIONS_PROVIDER = {"default": "typesafe"}

    def jev(state, questions, *, model, provider):
        return {
            q: Answer(
                id=q,
                value="built",
                confidence=0.97,
                probabilities={"built": 0.97},
                model=model,
                provider=provider,
            )
            for q in questions
        }

    post = ExperienceEntry(
        employer="EPFL",
        title="Research Intern",
        start_date=_date(2025, 6, 1),
        end_date=_date(2025, 9, 1),
        bullets=("Wrote the scripts for the group.", "A pipeline for the lab and the team."),
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "g-verb")
        _fact(student, confirmed=True)
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EXPERIENCE,
            payload=fact_payload(post, category=VerifiedFact.Category.EXPERIENCE),
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="upload:test",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )
        content = _content().model_copy(update={"experience": (post,)})
        result = generate_cv(student=student, client=_mock_client(content), decisions_client=jev)
    assert result.content.experience[0].bullets[1] == "Built a pipeline for the lab and the team."
    assert result.applied_fixes[-1].original == "A pipeline for the lab and the team."



