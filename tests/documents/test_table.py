from datetime import date
from uuid import uuid4

import pytest

from apps.documents.table import (
    ApplicationNeeds,
    Cell,
    Held,
    build_table,
    kinds_named,
    table_for,
)
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction


def _column(*sentences: str) -> ApplicationNeeds:
    return ApplicationNeeds(uuid4(), "TUM M.Sc.", tuple(sentences))


def _row(table, kind):
    return next(row for row in table.rows if row.kind == kind)


def test_kinds_are_read_from_the_programme_s_own_sentences() -> None:
    assert kinds_named("Upload your Bachelor's diploma and transcript of records.") == {
        "DIPLOMA",
        "TRANSCRIPT",
    }
    assert kinds_named("IELTS 6.5 or TOEFL iBT 90 is required.") == {"LANGUAGE_CERTIFICATE"}
    assert kinds_named("A CV in English (max. 2 pages).") == {"CV"}
    assert kinds_named("A statement of purpose.") == {"MOTIVATION_LETTER"}
    assert kinds_named("Applications open in October.") == set()
    assert kinds_named("Two letters of reference.") == {"RECOMMENDATION"}
    assert kinds_named("Two academic references.") == {"RECOMMENDATION"}
    for text in (
        "Reference number must be quoted.",
        "Courses with references to the syllabus.",
        "Cite references in your essay",
    ):
        assert "RECOMMENDATION" not in kinds_named(text)
    assert kinds_named("Proof of English.") == {"LANGUAGE_CERTIFICATE"}
    assert kinds_named("English language proficiency.") == {"LANGUAGE_CERTIFICATE"}
    assert kinds_named("English skills at B2.") == {"LANGUAGE_CERTIFICATE"}


def test_a_certified_copy_is_its_own_state_even_when_one_is_uploaded() -> None:
    column = _column("A certified copy of your diploma.")
    table = build_table([column], [Held("DIPLOMA", Cell.UPLOADED)])
    assert _row(table, "DIPLOMA").cells == (Cell.CERTIFIED,)


def test_one_upload_satisfies_every_application_that_needs_it() -> None:
    tum, kth = _column("Passport copy"), _column("A copy of your passport")
    table = build_table([tum, kth], [Held("PASSPORT", Cell.UPLOADED, expires_on=date(2030, 1, 1))])
    assert _row(table, "PASSPORT").cells == (Cell.UPLOADED, Cell.UPLOADED)
    assert _row(table, "PASSPORT").expires_on == date(2030, 1, 1)


def test_a_letter_belongs_to_one_application() -> None:
    tum, kth = _column("Motivation letter"), _column("Motivation letter")
    letter = Held("MOTIVATION_LETTER", Cell.APPROVED, application_id=tum.application_id)
    table = build_table([tum, kth], [letter])
    assert _row(table, "MOTIVATION_LETTER").cells == (Cell.APPROVED, Cell.MISSING)


def test_what_nobody_asked_for_is_not_needed() -> None:
    table = build_table([_column("Transcript")], [])
    assert _row(table, "PASSPORT").cells == (Cell.NOT_NEEDED,)
    assert _row(table, "TRANSCRIPT").cells == (Cell.MISSING,)


def test_counts_and_missing_labels_for_one_application() -> None:
    column = _column("Transcript", "CV", "Passport")
    table = build_table([column], [Held("CV", Cell.APPROVED)])
    assert table.counts_for(column.application_id) == (1, 3)
    assert table.missing_for(column.application_id) == ("Passport", "Transcript")
    assert table.held_for("CV", column.application_id) is not None
    assert table.held_for("PASSPORT", column.application_id) is None


def test_a_plain_upload_is_not_handed_back_for_a_certified_copy() -> None:
    column = _column("A certified copy of your diploma.")
    table = build_table([column], [Held("DIPLOMA", Cell.UPLOADED)])
    assert _row(table, "DIPLOMA").cells == (Cell.CERTIFIED,)
    assert table.held_for("DIPLOMA", column.application_id) is None


def test_the_certified_word_binds_only_its_own_clause() -> None:
    column = _column("Certified copies of diploma and transcript; a CV")
    table = build_table([column], [])
    assert _row(table, "DIPLOMA").cells == (Cell.CERTIFIED,)
    assert _row(table, "CV").cells == (Cell.MISSING,)


def test_a_certified_upload_satisfies_a_certified_copy_requirement() -> None:
    column = _column("A certified copy of your diploma.")
    held = Held("DIPLOMA", Cell.UPLOADED, certified=True)
    table = build_table([column], [held])
    assert _row(table, "DIPLOMA").cells == (Cell.UPLOADED,)
    assert table.held_for("DIPLOMA", column.application_id) == held


# table_for, against the database -------------------------------------------


def _world(agency, student, program_factory, *, apps=("TUM",)):
    from apps.portals.models import Application

    programmes = [program_factory() for _ in apps]
    applications = [
        Application.objects.create(
            tenant=agency,
            student=student,
            program_id=programme.id,
            name=name,
            kit_requirements=["CV", "Transcript"],
        )
        for programme, name in zip(programmes, apps, strict=True)
    ]
    return programmes, applications


def _cv(agency, student, programme=None, version=1):
    from apps.documents.models import DocumentDraft

    return DocumentDraft.objects.create(
        tenant=agency,
        student=student,
        kind=DocumentDraft.Kind.CV,
        version=version,
        content={},
        status=DocumentDraft.Status.APPROVED,
        programme=programme,
        # Rendered: table_for holds no draft the extension could not fetch yet.
        rendered_filename="cv-standard.pdf",
    )


def _upload(agency, student, kind="TRANSCRIPT", state="AVAILABLE"):
    from apps.concierge.models import DocumentVersion

    return DocumentVersion.objects.create(
        tenant=agency, student=student, object_key=f"k/{uuid4()}", kind=kind, state=state
    )


@pytest.mark.django_db
def test_another_student_s_documents_never_appear(
    agency_a, membership_a, program_factory, django_user_model
) -> None:
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a,
            user=django_user_model.objects.create_user(username="other-student"),
            role=Membership.Role.STUDENT,
        )
        programmes, applications = _world(agency_a, membership_a, program_factory)
        _cv(agency_a, other, programmes[0])
        _cv(agency_a, other, version=2)
        _upload(agency_a, other)
        table = table_for(membership_a, applications, [])
    assert table.held == ()
    assert set(table.missing_for(applications[0].id)) == {"CV", "Transcript"}


@pytest.mark.django_db
def test_an_upload_still_being_checked_does_not_count(
    agency_a, membership_a, program_factory
) -> None:
    """Task 14: shown as checking…, never held (no Submit) and never asked for again."""
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _, applications = _world(agency_a, membership_a, program_factory)
        _upload(agency_a, membership_a, state="CHECKING")
        table = table_for(membership_a, applications, [])
    assert [held.state for held in table.held] == [Cell.CHECKING]
    assert table.counts_for(applications[0].id)[0] == 0
    assert "Transcript" not in table.missing_for(applications[0].id)


@pytest.mark.django_db
def test_a_usable_upload_is_offered_before_a_re_upload_under_check(
    agency_a, membership_a, program_factory
) -> None:
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _, applications = _world(agency_a, membership_a, program_factory)
        usable = _upload(agency_a, membership_a)
        _upload(agency_a, membership_a, state="CHECKING")  # newer
        table = table_for(membership_a, applications, [])
    held = table.held_for("TRANSCRIPT", applications[0].id)
    assert held is not None and (held.document_id, held.state) == (usable.id, Cell.UPLOADED)


@pytest.mark.django_db
def test_a_cv_for_a_programme_with_no_application_is_offered_to_none(
    agency_a, membership_a, program_factory
) -> None:
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _, applications = _world(agency_a, membership_a, program_factory)
        _cv(agency_a, membership_a, program_factory())
        table = table_for(membership_a, applications, [])
    assert table.held == ()
    assert table.held_for("CV", applications[0].id) is None
    assert "CV" in table.missing_for(applications[0].id)


@pytest.mark.django_db
def test_an_application_s_own_cv_fills_only_its_own_cell(
    agency_a, membership_a, program_factory
) -> None:
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        programmes, applications = _world(
            agency_a, membership_a, program_factory, apps=("TUM", "KTH")
        )
        draft = _cv(agency_a, membership_a, programmes[0])
        table = table_for(membership_a, applications, [])
    tum, kth = applications
    assert table.held_for("CV", tum.id).document_id == draft.id
    assert table.held_for("CV", kth.id) is None
    assert _row(table, "CV").cells == (Cell.APPROVED, Cell.MISSING)


def test_an_upload_being_checked_is_shown_but_neither_held_nor_missing() -> None:
    column = _column("Passport copy")
    table = build_table([column], [Held("PASSPORT", Cell.CHECKING)])
    assert _row(table, "PASSPORT").cells == (Cell.CHECKING,)
    assert str(Cell.CHECKING) == "checking…"
    assert table.counts_for(column.application_id) == (0, 1)
    assert table.missing_for(column.application_id) == ()
