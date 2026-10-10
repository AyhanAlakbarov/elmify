"""build_kit: everything a human needs to apply by hand, and it never raises.

The kit is the layer that works with no extension, on any device. Where
mint_packet refuses, the kit degrades -- that asymmetry is the design.
"""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope
from tests.conftest import reads_no_catalogue

pytestmark = pytest.mark.django_db

ENTRIES = [
    {
        "profile_field": "identity.full_name",
        "action": {
            "selector": "#name",
            "description": "Full name",
            "method": "fill",
            "arguments": ["%value%"],
        },
    },
    {
        "profile_field": "personal.city",
        "action": {
            "selector": "#city",
            "description": "City of residence",
            "method": "fill",
            "arguments": ["%value%"],
        },
    },
]


def _application(agency, student, *, entries=ENTRIES, **form_kwargs):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"kit-{uuid4()}",
        form_url="https://apply.example.edu/personal",
        review_required=False,
        **form_kwargs,
    )
    if entries is not None:
        FieldMap.objects.create(portal_form=form, version=1, entries=entries)
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_the_kit_carries_the_portal_s_questions_in_the_portal_s_order(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        kit = packets.build_kit(application)

    assert [q.profile_field for q in kit.questions] == [
        "identity.full_name",
        "personal.city",
    ]
    assert [q.label for q in kit.questions] == ["Full name", "City of residence"]
    assert [q.answer for q in kit.questions] == ["Ada Byron", "London"]
    assert [q.missing for q in kit.questions] == [False, False]
    assert kit.not_fillable_reason == ""
    assert kit.portal_host == "apply.example.edu"
    assert kit.form_url == "https://apply.example.edu/personal"


def test_a_fact_we_do_not_hold_is_shown_as_missing_and_the_kit_is_still_built(
    agency_a, membership_a, monkeypatch
) -> None:
    """A missing fact refuses a packet. It must not refuse a kit: the student
    can still answer that one field by hand, and hiding the rest helps nobody."""
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)

        kit = packets.build_kit(application)

    assert [(q.profile_field, q.missing) for q in kit.questions] == [
        ("identity.full_name", False),
        ("personal.city", True),
    ]
    assert kit.questions[1].answer == ""


def test_a_malformed_field_map_entry_is_skipped_not_raised(
    agency_a, membership_a, monkeypatch
) -> None:
    """FieldMap is a shared table this plan never writes, so its row shape is
    not build_kit's to assume. build_kit's docstring promises it never raises;
    a row missing profile_field must be skipped, not crash the whole kit."""
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    malformed = [
        {"action": {"selector": "#mystery", "description": "No profile_field key"}},
        {
            "profile_field": "identity.full_name",
            "action": {
                "selector": "#name",
                "description": "Full name",
                "method": "fill",
                "arguments": ["%value%"],
            },
        },
    ]
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=malformed)

        kit = packets.build_kit(application)

    assert [q.profile_field for q in kit.questions] == ["identity.full_name"]
    assert kit.not_fillable_reason == ""


def test_a_portal_whose_terms_prohibit_automation_still_gets_a_kit(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets
    from apps.portals.models import PortalForm

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a,
            membership_a,
            terms_posture=PortalForm.TermsPosture.PROHIBITS_AUTOMATION,
        )

        kit = packets.build_kit(application)

    assert len(kit.questions) == 2
    assert kit.not_fillable_reason == "automation_prohibited"


def _statement(program, text, *, kind="DOCUMENT", requirement="REQUIRED"):
    from django.utils import timezone

    from apps.funding.models import (
        OfficialSource,
        OfficialSourceSnapshot,
        ProgramStatement,
    )

    source = OfficialSource.objects.create(
        canonical_url=f"https://official.example/{uuid4()}",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key=f"official-sources/{uuid4()}",
        s3_version_id="1",
        sha256="a" * 64,
        final_url=source.canonical_url,
        redirect_chain=[],
        retrieved_at=timezone.now(),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=1,
    )
    return ProgramStatement.objects.create(
        program=program,
        snapshot=snapshot,
        kind=kind,
        requirement=requirement,
        text=text,
        label=text[:40],
    )


def test_without_a_field_map_the_kit_shows_what_we_hold_and_the_programme_checklist(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    """No map means we do not know the portal's questions. Inventing them is
    the one dishonest thing a kit could do, so it shows our answers instead."""
    from apps.portals import packets
    from apps.portals.models import Application, PortalForm

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"personal.city": "London", "identity.full_name": "Ada Byron"},
    )
    program = program_factory()
    _statement(program, "Submit a curriculum vitae.")
    _statement(program, "A motivation letter is desired.", requirement="DESIRED")

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(
            portal_host="apply.example.edu",
            form_key=f"kit-nomap-{uuid4()}",
            form_url="https://apply.example.edu/personal",
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=program.id, portal_form=form
        )
        packets.capture_requirements(application)

        kit = packets.build_kit(application)

    assert kit.not_fillable_reason == "no_field_map"
    # Stable order, so two reads of one kit do not shuffle under the student.
    assert [q.profile_field for q in kit.questions] == [
        "identity.full_name",
        "personal.city",
    ]
    # Read by a person: never the raw "category.key" (Task 19 minor).
    assert [q.label for q in kit.questions] == ["Identity: full name", "Personal: city"]
    assert all(q.missing is False for q in kit.questions)
    # REQUIRED only: a DESIRED statement is not a checklist item.
    assert kit.requirements == ("Submit a curriculum vitae.",)


def test_a_kit_for_a_programme_we_have_never_read_has_an_empty_checklist(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, entries=None)
        packets.capture_requirements(application)

        kit = packets.build_kit(application)

    assert kit.requirements == ()
    assert kit.questions == ()


def _approved_cv(agency, student, programme=None, rendered_filename="cv-standard.pdf"):
    from apps.documents.models import DocumentDraft

    # rendered_filename stands in for storage.store_document having put the
    # artefact; the kit lists only drafts that have one.
    return DocumentDraft.objects.create(
        tenant=agency,
        student=student,
        kind=DocumentDraft.Kind.CV,
        version=1,
        content={},
        status=DocumentDraft.Status.APPROVED,
        programme=programme,
        rendered_filename=rendered_filename,
    )


def test_the_kit_links_approved_documents_through_the_download_route(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    from apps.portals import packets
    from apps.portals.models import Application, FieldMap, PortalForm

    monkeypatch.setattr(
        packets,
        "verified_values",
        lambda student: {"identity.full_name": "Ada Byron", "personal.city": "London"},
    )
    # A "US" programme would resolve live to STANDARD. The link must name what
    # was actually stored instead: the object's name is fixed at render time.
    program = program_factory(country_code="US")
    with tenant_scope(agency_a.id):
        draft = _approved_cv(
            agency_a, membership_a, programme=program, rendered_filename="cv-german-tabular.pdf"
        )
        form = PortalForm.objects.create(
            portal_host="apply.example.edu",
            form_key=f"kit-docs-{uuid4()}",
            form_url="https://apply.example.edu/personal",
        )
        FieldMap.objects.create(portal_form=form, version=1, entries=ENTRIES)
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=program.id, portal_form=form
        )

        kit = packets.build_kit(application)

    assert [d.draft_id for d in kit.documents] == [draft.id]
    assert kit.documents[0].filename == "cv-german-tabular.pdf"
    assert kit.documents[0].download_path == f"/documents/{draft.id}/cv-german-tabular.pdf"
    assert kit.documents[0].label == "CV"


def test_an_approved_cv_not_yet_rendered_is_not_in_the_kit(
    agency_a, membership_a, monkeypatch
) -> None:
    """No stored artefact means no name to link to; linking a guessed one is
    how the kit used to point at objects that did not exist."""
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        _approved_cv(agency_a, membership_a, rendered_filename="")
        kit = packets.build_kit(_application(agency_a, membership_a))
    assert kit.documents == ()


def test_an_approved_core_narrative_does_not_appear_in_the_kit(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    """CORE_NARRATIVE is an internal artefact with no stored render and no
    filename shape artefact_filename understands -- it must never reach a
    portal-facing kit, approved or not."""
    from apps.documents.models import DocumentDraft
    from apps.portals import packets
    from apps.portals.models import Application, PortalForm

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    program = program_factory(country_code="US")
    with tenant_scope(agency_a.id):
        DocumentDraft.objects.create(
            tenant=agency_a,
            student=membership_a,
            kind=DocumentDraft.Kind.CORE_NARRATIVE,
            version=1,
            content={},
            status=DocumentDraft.Status.APPROVED,
            programme=program,
        )
        form = PortalForm.objects.create(
            portal_host="apply.example.edu", form_key=f"kit-narrative-{uuid4()}"
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=program.id, portal_form=form
        )

        kit = packets.build_kit(application)

    assert kit.documents == ()


def test_an_unapproved_draft_is_not_in_the_kit(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    """The download route refuses anything not APPROVED, so listing one would
    be a link that 404s -- and a counselor's unfinished draft is not something
    to put in front of a portal."""
    from apps.documents.models import DocumentDraft
    from apps.portals import packets
    from apps.portals.models import Application, PortalForm

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    program = program_factory()
    with tenant_scope(agency_a.id):
        DocumentDraft.objects.create(
            tenant=agency_a,
            student=membership_a,
            kind=DocumentDraft.Kind.CV,
            version=1,
            content={},
            render_variant=DocumentDraft.RenderVariant.STANDARD,
            status=DocumentDraft.Status.DRAFT,
            programme=program,
        )
        form = PortalForm.objects.create(
            portal_host="apply.example.edu", form_key=f"kit-unapproved-{uuid4()}"
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=program.id, portal_form=form
        )

        kit = packets.build_kit(application)

    assert kit.documents == ()


def test_another_programme_s_document_is_not_in_this_application_s_kit(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    from apps.portals import packets
    from apps.portals.models import Application, PortalForm

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    mine, theirs = program_factory(), program_factory()
    with tenant_scope(agency_a.id):
        _approved_cv(agency_a, membership_a, programme=theirs)
        form = PortalForm.objects.create(
            portal_host="apply.example.edu", form_key=f"kit-other-{uuid4()}"
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=mine.id, portal_form=form
        )

        kit = packets.build_kit(application)

    assert kit.documents == ()


def test_a_programme_agnostic_document_is_in_every_kit(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    """A CV generated without a programme is the student's general one and
    applies everywhere; dropping it would leave a kit with no CV at all."""
    from apps.portals import packets
    from apps.portals.models import Application, PortalForm

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    program = program_factory()
    with tenant_scope(agency_a.id):
        draft = _approved_cv(agency_a, membership_a, programme=None)
        form = PortalForm.objects.create(
            portal_host="apply.example.edu", form_key=f"kit-generic-{uuid4()}"
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=program.id, portal_form=form
        )

        kit = packets.build_kit(application)

    assert [d.draft_id for d in kit.documents] == [draft.id]


@pytest.mark.django_db(transaction=True)
def test_build_kit_sets_its_own_guc_with_no_http_request(
    agency_a, membership_a, rls_enforced_orm
) -> None:
    """build_kit is called from places that are not HTTP requests -- a worker,
    a management command, another service -- where there is no
    apps.tenancy.middleware opening a transaction and setting app.tenant_id
    first. Its own tenant_transaction has to do that, or a caller with no
    middleware gets an empty kit under RLS enforcement and no error at all.

    tenant_scope alone is a ContextVar and sets nothing in Postgres (see
    apps/portals/services.py's own comment), so this test deliberately holds
    tenant_scope but no surrounding tenant_transaction around the build_kit
    call: it passes only because build_kit opens one itself.
    """
    from django.utils import timezone

    from apps.documents.models import VerifiedFact
    from apps.portals import packets
    from apps.tenancy.db import tenant_transaction

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        application = _application(agency_a, membership_a)
        VerifiedFact.objects.create(
            tenant=agency_a,
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Ada Byron"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="passport.pdf",
            confirmed_by=membership_a,
            confirmed_at=timezone.now(),
            created_by=membership_a,
        )

    with tenant_scope(agency_a.id):
        kit = packets.build_kit(application)

    assert [q.answer for q in kit.questions if q.profile_field == "identity.full_name"] == [
        "Ada Byron"
    ]


def _letter_prompt(program, cycle, **overrides):
    from apps.funding.models import ApplicationPrompt

    fields = dict(
        programme=program,
        cycle=cycle,
        source_url="https://example.test/apply",
        confidence=1.0,
        source=ApplicationPrompt.Source.EXTRACTED,
        funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        document_language="en",
        letter_handwritten=True,
        letter_shape_sources={
            "handwritten": {
                "text": f"The letter must be handwritten ({cycle}).",
                "source_url": "https://example.test/apply",
            },
            "max_words": {
                "text": "no more than 500 words",
                "source_url": "https://example.test/apply",
            },
        },
        letter_student_actions=[
            {"text": "Sign it in ink.", "source_url": "https://example.test/apply"}
        ],
    )
    fields.update(overrides)
    return ApplicationPrompt.objects.create(**fields)


def test_the_kit_carries_the_letter_steps_only_the_applicant_can_take(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    """Nothing in this system can sign a letter in ink.

    `apps/funding/requirements.py` named this seam when the kit was designed
    and it was never wired, so a page requiring a hand-signed letter reached
    the letter pane and never the kit the student applies from. Only the
    YOUR_ACTION items: a word cap is enforced at render and belongs nowhere
    near a human checklist.
    """
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="DE")
        _letter_prompt(program, "2026")
        _letter_prompt(program, "2027")
        application = _application(agency_a, membership_a)
        application.program_id = program.id
        application.save(update_fields=["program_id"])
        packets.capture_requirements(application)

        kit = packets.build_kit(application)

    # The newest cycle, and the kit says which one it read.
    assert kit.letter_cycle == "2027"
    assert [item.text for item in kit.your_actions] == [
        "The letter must be handwritten (2027).",
        "Sign it in ink.",
    ]
    assert all(item.source_url == "https://example.test/apply" for item in kit.your_actions)


def test_a_programme_with_no_prompt_has_no_letter_steps_and_still_builds(
    agency_a, membership_a, monkeypatch
) -> None:
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        packets.capture_requirements(application)
        kit = packets.build_kit(application)
    assert kit.your_actions == () and kit.letter_cycle == ""


def test_unreadable_catalog_json_costs_the_steps_and_not_the_kit(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    """`letter_shape_sources` is catalog JSON, and a kit that 500s because a
    shared-catalog row is malformed is worse than a kit with no letter steps.
    A list where a dict belongs is the cheapest way to say "unreadable"."""
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        program = program_factory(country_code="DE")
        _letter_prompt(program, "2027", letter_shape_sources={"handwritten": ["not", "a", "dict"]})
        application = _application(agency_a, membership_a)
        application.program_id = program.id
        application.save(update_fields=["program_id"])
        packets.capture_requirements(application)

        kit = packets.build_kit(application)

    assert kit.your_actions == ()
    # The cycle still reports which prompt failed to read.
    assert kit.letter_cycle == "2027"
    assert kit.questions


def test_capturing_reads_the_catalogue_and_serving_the_kit_does_not(
    agency_a, membership_a, program_factory, monkeypatch
) -> None:
    """The copy-forward the catalog read split rests on.

    capture_requirements is worker work and may read ProgramStatement and
    ApplicationPrompt; build_kit is served by a web view whose role holds no
    grant on the catalogue. Proved on the SQL actually sent, not by mocking
    the readers out: the default test role is a superuser and would read the
    catalogue happily, so the only honest check is which tables the kit's
    queries name.
    """
    from apps.funding.requirements import RequirementItem
    from apps.portals import packets
    from apps.portals.models import Application

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    program = program_factory(country_code="DE")
    _statement(program, "Submit a curriculum vitae.")
    _letter_prompt(program, "2027")
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        application.program_id = program.id
        application.save(update_fields=["program_id"])
        packets.capture_requirements(application)
        _approved_cv(agency_a, membership_a, programme=program)

        stored = Application.objects.get(id=application.id)
        with reads_no_catalogue():
            kit = packets.build_kit(stored)

    assert kit.requirements == ("Submit a curriculum vitae.",)
    assert len(kit.documents) == 1
    assert kit.letter_cycle == "2027"
    assert kit.your_actions and all(isinstance(i, RequirementItem) for i in kit.your_actions)
    assert kit.your_actions[0].source_url == "https://example.test/apply"


def test_a_kit_never_captured_is_empty_not_an_error(agency_a, membership_a, monkeypatch) -> None:
    """Nothing in production calls capture_requirements yet, so an empty copy
    is the kit every application gets today: the same degrade as an unread
    programme. A stored action this code cannot read degrades the same way."""
    from apps.portals import packets

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
        application.kit_your_actions = [{"not": "a RequirementItem"}]
        kit = packets.build_kit(application)
    assert kit.requirements == () and kit.your_actions == () and kit.letter_cycle == ""
    assert kit.questions
