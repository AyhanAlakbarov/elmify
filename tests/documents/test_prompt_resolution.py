from unittest.mock import MagicMock

import pytest

from apps.documents.prompt_resolution import (
    _RESOLUTION_LIMIT,
    LetterPromptExtraction,
    PromptResolutionRateLimited,
    resolve_application_prompt,
)
from apps.funding.models import ApplicationPrompt, AuditEvent
from apps.research.extraction import SourceSnapshot
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _mock_client(**extraction_kwargs):
    client = MagicMock()
    response = MagicMock()
    response.output_parsed = LetterPromptExtraction(
        confidence=extraction_kwargs.pop("confidence", 0.9), **extraction_kwargs
    )
    response.output = []
    client.responses.parse.return_value = response
    return client


def test_existing_verified_row_is_returned_unchanged(program_factory):
    program = program_factory()
    verified = ApplicationPrompt.objects.create(
        programme=program,
        cycle="2027",
        source_url="https://daad.de",
        confidence=1.0,
        verified_for_cycle="2027",
        source=ApplicationPrompt.Source.VERIFIED,
        funder_kind=ApplicationPrompt.FunderKind.GOVERNMENT_SCHOLARSHIP,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        archetypes=["WHY_COUNTRY"],
        questions=[],
        programme_evidence={},
        document_language="en",
    )
    client = _mock_client(
        structure="SHORT_ANSWER_SET",
        funder_kind="UNIVERSITY_ADMISSION",
        letter_required="required",
        document_language="en",
    )
    resolved = resolve_application_prompt(
        program=program, cycle="2027", snapshot=SourceSnapshot(relevant_text="x"), client=client
    )
    assert resolved.id == verified.id
    client.responses.parse.assert_not_called()


def test_verified_row_for_an_old_cycle_does_not_short_circuit(program_factory):
    # PF-7: a VERIFIED row is only a valid short-circuit for the cycle it was
    # actually verified for. Without this, a row verified for 2026 would keep
    # driving 2027 resolutions and the ladder would never re-resolve.
    program = program_factory()
    ApplicationPrompt.objects.create(
        programme=program,
        cycle="2026",
        source_url="https://daad.de",
        confidence=1.0,
        verified_for_cycle="2026",
        source=ApplicationPrompt.Source.VERIFIED,
        funder_kind=ApplicationPrompt.FunderKind.GOVERNMENT_SCHOLARSHIP,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        archetypes=["WHY_COUNTRY"],
        questions=[],
        programme_evidence={},
        document_language="en",
    )
    client = _mock_client(
        structure="TWO_STATEMENTS",
        funder_kind="UNIVERSITY_ADMISSION",
        letter_required="required",
        document_language="en",
        confidence=0.85,
    )
    resolved = resolve_application_prompt(
        program=program, cycle="2027", snapshot=SourceSnapshot(relevant_text="x"), client=client
    )
    assert resolved.source == ApplicationPrompt.Source.EXTRACTED
    client.responses.parse.assert_called_once()


def test_high_confidence_extraction_creates_extracted_row(program_factory):
    program = program_factory()
    client = _mock_client(
        structure="TWO_STATEMENTS",
        funder_kind="UNIVERSITY_ADMISSION",
        letter_required="required",
        document_language="en",
        confidence=0.85,
    )
    resolved = resolve_application_prompt(
        program=program, cycle="2027", snapshot=SourceSnapshot(relevant_text="x"), client=client
    )
    assert resolved.source == ApplicationPrompt.Source.EXTRACTED
    assert resolved.structure == ApplicationPrompt.Structure.TWO_STATEMENTS


def test_low_confidence_extraction_falls_to_inferred_with_silent_funder_defaults(program_factory):
    program = program_factory()
    client = _mock_client(
        structure=None,
        funder_kind="GOVERNMENT_SCHOLARSHIP",
        letter_required=None,
        document_language=None,
        confidence=0.3,
    )
    resolved = resolve_application_prompt(
        program=program, cycle="2027", snapshot=SourceSnapshot(relevant_text="x"), client=client
    )
    assert resolved.source == ApplicationPrompt.Source.INFERRED
    assert resolved.structure == ApplicationPrompt.Structure.CONTINUOUS_LETTER
    assert "WHY_COUNTRY" in resolved.archetypes


def test_no_snapshot_and_no_prior_row_creates_unresolved_with_audit_event(
    program_factory, agency_a
):
    # PF-5: record_event returns None (and writes nothing) outside a tenant
    # scope, since AuditEvent is tenant-scoped -- so this assertion is only
    # meaningful inside tenant_scope(agency_a.id).
    with tenant_scope(agency_a.id):
        program = program_factory()
        resolved = resolve_application_prompt(
            program=program, cycle="2027", snapshot=None, client=None
        )
        assert resolved.source == ApplicationPrompt.Source.UNRESOLVED
        assert resolved.structure == ApplicationPrompt.Structure.CONTINUOUS_LETTER
        assert AuditEvent.objects.filter(
            object_id=program.id, event="document.prompt_unresolved"
        ).exists()


def test_extracted_row_for_immigration_authority_funder_sets_immigration_true(program_factory):
    """FIX (review round 1): apply_silent_funder_defaults / the EXTRACTED rung
    both branch on funder_kind == IMMIGRATION_AUTHORITY, and the row must
    carry that same conclusion forward as immigration=True, or the
    no-override UNCERTAIN-blocks rule (letter_verification's immigration
    param feeding is_letter_blocked) never engages for a prompt this ladder
    produced automatically."""
    program = program_factory()
    client = _mock_client(
        structure="SHORT_ANSWER_SET",
        funder_kind="IMMIGRATION_AUTHORITY",
        letter_required="required",
        document_language="en",
        confidence=0.9,
    )
    resolved = resolve_application_prompt(
        program=program, cycle="2027", snapshot=SourceSnapshot(relevant_text="x"), client=client
    )
    assert resolved.source == ApplicationPrompt.Source.EXTRACTED
    assert resolved.immigration is True


def test_extracted_row_for_non_immigration_funder_sets_immigration_false(program_factory):
    program = program_factory()
    client = _mock_client(
        structure="TWO_STATEMENTS",
        funder_kind="UNIVERSITY_ADMISSION",
        letter_required="required",
        document_language="en",
        confidence=0.85,
    )
    resolved = resolve_application_prompt(
        program=program, cycle="2027", snapshot=SourceSnapshot(relevant_text="x"), client=client
    )
    assert resolved.source == ApplicationPrompt.Source.EXTRACTED
    assert resolved.immigration is False


def test_inferred_row_for_immigration_authority_funder_sets_immigration_true(program_factory):
    program = program_factory()
    client = _mock_client(
        structure=None,
        funder_kind="IMMIGRATION_AUTHORITY",
        letter_required=None,
        document_language=None,
        confidence=0.3,
    )
    resolved = resolve_application_prompt(
        program=program, cycle="2027", snapshot=SourceSnapshot(relevant_text="x"), client=client
    )
    assert resolved.source == ApplicationPrompt.Source.INFERRED
    assert resolved.immigration is True


def test_invalid_funder_kind_falls_back_to_safe_default_without_integrity_error(program_factory):
    """FIX (review round 1): a hallucinated funder_kind must not reach
    ApplicationPrompt.objects.create() unvalidated -- it would hit the
    applicationprompt_funder_kind_valid CheckConstraint as an uncaught
    IntegrityError instead of resolving cleanly."""
    program = program_factory()
    client = _mock_client(
        structure="TWO_STATEMENTS",
        funder_kind="NOT_A_REAL_FUNDER_KIND",
        letter_required="required",
        document_language="en",
        confidence=0.95,
    )
    resolved = resolve_application_prompt(
        program=program, cycle="2027", snapshot=SourceSnapshot(relevant_text="x"), client=client
    )
    assert resolved.source == ApplicationPrompt.Source.EXTRACTED
    assert resolved.funder_kind == ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION
    assert resolved.immigration is False


def test_resolving_the_same_programme_and_cycle_twice_updates_one_row(program_factory):
    """Every rung used to create() unconditionally, so re-resolving a
    programme left duplicate shared-catalog rows with nothing saying which
    one a letter should use -- and, because the real cycle was never
    written, _existing_verified's cycle filter could never match one of
    them either."""
    program = program_factory()
    snapshot = SourceSnapshot(relevant_text="x")
    first = resolve_application_prompt(
        program=program,
        cycle="2027",
        snapshot=snapshot,
        client=_mock_client(structure="SHORT_ANSWER_SET", funder_kind="UNIVERSITY_ADMISSION"),
    )
    second = resolve_application_prompt(
        program=program,
        cycle="2027",
        snapshot=snapshot,
        client=_mock_client(structure="TWO_STATEMENTS", funder_kind="UNIVERSITY_ADMISSION"),
    )
    assert first.id == second.id
    assert ApplicationPrompt.objects.filter(programme=program).count() == 1
    # The real cycle reaches the row -- it used to be written as "".
    assert second.cycle == "2027"
    # And the re-read's answer wins rather than being discarded.
    assert second.structure == ApplicationPrompt.Structure.TWO_STATEMENTS


def test_a_second_unresolved_resolution_records_only_one_counselor_event(
    program_factory, agency_a
):
    """The audit event puts a programme in front of a counselor once, not
    once per retry. AuditEvent is tenant-scoped, so this only means anything
    inside tenant_scope (PF-5)."""
    with tenant_scope(agency_a.id):
        program = program_factory()
        resolve_application_prompt(program=program, cycle="2027")
        resolve_application_prompt(program=program, cycle="2027")
        assert ApplicationPrompt.objects.filter(programme=program).count() == 1
        assert (
            AuditEvent.objects.filter(
                object_id=program.id, event="document.prompt_unresolved"
            ).count()
            == 1
        )


@pytest.mark.parametrize("junk", ["Deutsch (German)", "en_US_lots_of_junk", "", "1234"])
def test_a_junk_document_language_falls_back_instead_of_reaching_the_column(
    program_factory, junk
):
    """document_language is model-supplied and its column is a bare
    CharField(10) with no CheckConstraint -- unlike structure and
    funder_kind. Over ten characters it is a DataError at write time; under
    ten it writes cleanly and produces a letter that can never pass
    check_language_mismatch, because content.language will never equal it.
    """
    program = program_factory()
    resolved = resolve_application_prompt(
        program=program,
        cycle="2027",
        snapshot=SourceSnapshot(relevant_text="x"),
        client=_mock_client(
            structure="SHORT_ANSWER_SET",
            funder_kind="UNIVERSITY_ADMISSION",
            document_language=junk,
        ),
    )
    assert resolved.document_language == "en"


def test_a_plausible_document_language_is_kept(program_factory):
    program = program_factory()
    resolved = resolve_application_prompt(
        program=program,
        cycle="2027",
        snapshot=SourceSnapshot(relevant_text="x"),
        client=_mock_client(
            structure="SHORT_ANSWER_SET",
            funder_kind="UNIVERSITY_ADMISSION",
            document_language="de",
        ),
    )
    assert resolved.document_language == "de"


def test_prompt_resolution_is_rate_limited_per_programme(program_factory, settings):
    """Every other LLM-calling entry point on this branch carries its own
    bucket; this one had none, so a catalog sweep could call the model
    without any ceiling at all."""
    program = program_factory()
    snapshot = SourceSnapshot(relevant_text="x")
    client = _mock_client(structure="SHORT_ANSWER_SET", funder_kind="UNIVERSITY_ADMISSION")
    for _ in range(_RESOLUTION_LIMIT):
        resolve_application_prompt(
            program=program, cycle="2027", snapshot=snapshot, client=client
        )
    with pytest.raises(PromptResolutionRateLimited):
        resolve_application_prompt(
            program=program, cycle="2027", snapshot=snapshot, client=client
        )
    # The budget is per programme, not global: a different programme is
    # unaffected.
    other = resolve_application_prompt(
        program=program_factory(), cycle="2027", snapshot=snapshot, client=client
    )
    assert other.source == ApplicationPrompt.Source.EXTRACTED


def test_the_rate_limit_does_not_charge_a_verified_short_circuit(program_factory):
    """A cached VERIFIED hit makes no model call, so it must not spend the
    programme's budget."""
    program = program_factory()
    ApplicationPrompt.objects.create(
        programme=program,
        cycle="2027",
        source_url="https://daad.de",
        confidence=1.0,
        verified_for_cycle="2027",
        source=ApplicationPrompt.Source.VERIFIED,
        funder_kind=ApplicationPrompt.FunderKind.GOVERNMENT_SCHOLARSHIP,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        archetypes=["WHY_COUNTRY"],
        questions=[],
        programme_evidence={},
        document_language="en",
    )
    snapshot = SourceSnapshot(relevant_text="x")
    client = _mock_client(structure="SHORT_ANSWER_SET", funder_kind="UNIVERSITY_ADMISSION")
    for _ in range(_RESOLUTION_LIMIT + 2):
        resolve_application_prompt(
            program=program, cycle="2027", snapshot=snapshot, client=client
        )
    client.responses.parse.assert_not_called()


def test_a_failed_resolution_never_overwrites_an_already_resolved_row(program_factory):
    """ApplicationPrompt is shared-catalog data: every tenant reads the row.
    _create_unresolved therefore uses get_or_create, not update_or_create --
    a later attempt with no snapshot to read must leave an EXTRACTED row
    standing rather than replacing it with an UNRESOLVED placeholder that
    nothing audits and no tenant asked for."""
    program = program_factory()
    resolved = resolve_application_prompt(
        program=program,
        cycle="2027",
        snapshot=SourceSnapshot(relevant_text="x"),
        client=_mock_client(structure="TWO_STATEMENTS", funder_kind="UNIVERSITY_ADMISSION"),
    )
    assert resolved.source == ApplicationPrompt.Source.EXTRACTED

    after = resolve_application_prompt(program=program, cycle="2027", snapshot=None, client=None)

    assert after.id == resolved.id
    assert after.source == ApplicationPrompt.Source.EXTRACTED
    assert after.structure == ApplicationPrompt.Structure.TWO_STATEMENTS
    assert ApplicationPrompt.objects.filter(programme=program).count() == 1


def test_an_inferred_row_takes_the_programmes_own_mode_not_the_fallback(program_factory):
    """The page was unreadable; the COUNTRY was never in doubt.

    `apply_silent_funder_defaults` has taken country, track and portfolio-led
    since Task 6 and this caller passed none of them, so every inferred prompt
    got the fallback system's shape -- the UK/US essay order and its word
    target -- whatever country the programme was in. Japan's row orders
    ACADEMIC_PREPARATION first and targets 750 words; the fallback orders
    WHY_PROGRAMME first and targets 550.
    """
    japan = program_factory(country_code="JP", location_key="jp:tokyo", city="Tokyo")
    client = _mock_client(
        structure=None,
        funder_kind="UNIVERSITY_ADMISSION",
        letter_required=None,
        document_language=None,
        confidence=0.3,
    )
    resolved = resolve_application_prompt(
        program=japan, cycle="2027", snapshot=SourceSnapshot(relevant_text="x"), client=client
    )
    assert resolved.source == ApplicationPrompt.Source.INFERRED
    assert resolved.archetypes[0] == "ACADEMIC_PREPARATION"
    # The word target the same defaults compute is NOT asserted, because
    # _create_inferred never stores it: `apply_silent_funder_defaults` returns
    # a "constraints" entry that this caller drops on the floor. Recorded here
    # rather than fixed at merge time -- storing it would put a new
    # ADVISORY_STYLE rule on every inferred prompt, which is a decision, not a
    # cleanup.
    fallback = program_factory(country_code="GB", location_key="gb:london", city="London")
    other = resolve_application_prompt(
        program=fallback, cycle="2027", snapshot=SourceSnapshot(relevant_text="x"), client=client
    )
    assert other.archetypes[0] == "WHY_PROGRAMME"
