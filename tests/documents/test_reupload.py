from datetime import date
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.documents.models import VerifiedFact
from apps.documents.reupload import (
    chains,
    has_pending_changes,
    merged_payload,
    pending_changes,
    plan_upload,
    settle_changes,
)
from apps.documents.schemas import EducationEntry, ExperienceEntry
from apps.documents.verification import (
    fact_identity,
    fact_payload,
    generatable_facts,
    unsuperseded_facts,
)
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

EDU = VerifiedFact.Category.EDUCATION
EXP = VerifiedFact.Category.EXPERIENCE


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _degree(**over):
    fields = {
        "degree_as_awarded": "B.Sc. of Chem. Eng.",
        "institution_original": "UFAZ",
        "city": "Baku",
        "country": "AZ",
        "start_date": date(2019, 9, 1),
        "end_date": date(2023, 6, 1),
    }
    fields.update(over)
    return fact_payload(EducationEntry(**fields), category=EDU)


def _fact(
    student,
    payload,
    *,
    category=EDU,
    confirmed=True,
    supersedes=None,
    tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
    ref="upload:first",
):
    return VerifiedFact.objects.create(
        student=student,
        category=category,
        payload=payload,
        source_tier=tier,
        source_ref=ref,
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
        supersedes=supersedes,
        created_by=student,
    )


def test_fact_identity_is_the_verifiers_identity():
    payload = _degree()
    assert fact_identity(EDU, payload) == ("ufaz", "b.sc. of chem. eng.")
    assert fact_identity("NO_SUCH_CATEGORY", payload) == ()


def test_a_chain_lists_its_tip_then_every_older_row(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "chain")
        old = _fact(student, _degree())
        new = _fact(
            student,
            _degree(degree_as_awarded="Bachelor of Chemical Engineering"),
            supersedes=old,
            ref="gap-interview",
        )
        found = chains(student, EDU)
    assert len(found) == 1
    assert found[0].tip.id == new.id
    assert [row.id for row in found[0].rows] == [new.id, old.id]


def test_a_changed_date_supersedes_the_matching_fact(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "changed")
        old = _fact(student, _degree())
        writes = plan_upload(EDU, [_degree(end_date=date(2023, 7, 1))], chains(student, EDU))
    assert len(writes) == 1
    assert writes[0].supersedes is not None and writes[0].supersedes.id == old.id
    assert writes[0].payload["end_date"] == "2023-07-01"


def test_an_unchanged_entry_writes_nothing(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "same")
        _fact(student, _degree())
        assert plan_upload(EDU, [_degree()], chains(student, EDU)) == []


def test_a_new_entry_is_added_and_an_old_only_entry_stays(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "added")
        _fact(student, _degree())
        msc = _degree(degree_as_awarded="MSc Chemoinformatics", institution_original="Unistra")
        writes = plan_upload(EDU, [msc], chains(student, EDU))
    assert len(writes) == 1
    assert writes[0].supersedes is None
    assert writes[0].payload["degree_as_awarded"] == "MSc Chemoinformatics"


def test_a_corrected_title_survives_a_reupload_of_the_abbreviation(
    agency_a, django_user_model
):
    """Matching runs over the whole chain (spec §4): the old abbreviation still
    names this degree, and it is a value the chain already moved away from."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "corrected")
        old = _fact(student, _degree())
        _fact(
            student,
            _degree(degree_as_awarded="Bachelor of Chemical Engineering"),
            supersedes=old,
            ref="gap-interview",
        )
        assert plan_upload(EDU, [_degree()], chains(student, EDU)) == []


def test_a_blank_in_the_new_cv_never_wipes_a_stored_value(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "blank")
        _fact(student, _degree())
        assert plan_upload(EDU, [_degree(city=None, end_date=None)], chains(student, EDU)) == []


def test_merged_payload_keeps_what_only_the_ledger_knows(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "merge")
        _fact(student, {**_degree(), "thesis_title": "AZIMUTH"})
        merged = merged_payload(chains(student, EDU)[0], _degree(end_date=date(2023, 7, 1)))
    assert merged["thesis_title"] == "AZIMUTH"
    assert merged["end_date"] == "2023-07-01"


def test_two_posts_with_one_identity_claim_two_chains(agency_a, django_user_model):
    def post(start):
        return fact_payload(
            ExperienceEntry(
                employer="SOCAR",
                title="Intern",
                start_date=start,
                bullets=("Logged well data.",),
            ),
            category=EXP,
        )

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "twins")
        first = _fact(student, post(date(2021, 6, 1)), category=EXP)
        second = _fact(student, post(date(2022, 6, 1)), category=EXP)
        writes = plan_upload(
            EXP,
            [post(date(2021, 6, 1)), post(date(2022, 7, 1))],
            chains(student, EXP),
        )
    # The unchanged post claims its own chain by start date; the changed one
    # takes the other chain instead of becoming a third post.
    assert [w.supersedes.id for w in writes] == [second.id]
    assert first.id not in {w.supersedes.id for w in writes}


def test_an_authoritative_tip_is_never_superseded_by_a_cv(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "diploma")
        _fact(
            student,
            _degree(),
            tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            ref="diploma:1",
        )
        assert plan_upload(EDU, [_degree(end_date=date(2023, 7, 1))], chains(student, EDU)) == []


def test_a_renamed_identity_matches_the_one_identity_chain(agency_a, django_user_model):
    ident = VerifiedFact.Category.IDENTITY
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "named")
        old = _fact(student, {"full_name": "Orxan Abdullayev"}, category=ident)
        writes = plan_upload(ident, [{"full_name": "Orkhan Abdullayev"}], chains(student, ident))
    assert len(writes) == 1 and writes[0].supersedes.id == old.id


def _pending(student):
    """A confirmed degree, then an upload row changing its end date."""
    old = _fact(student, _degree())
    new = _fact(
        student,
        _degree(end_date=date(2023, 7, 1)),
        supersedes=old,
        confirmed=False,
        ref="upload:second",
    )
    return old, new


def test_a_change_to_a_confirmed_fact_is_pending(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "pending")
        old, new = _pending(student)
        [change] = pending_changes(student)
        assert has_pending_changes(student)
    assert change.fact.id == new.id and change.kept.id == old.id
    assert change.changes == (("end_date", "2023-06-01", "2023-07-01"),)


def test_a_new_entry_or_a_gap_answer_is_not_a_pending_change(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "notpending")
        _fact(student, _degree(), confirmed=False, ref="upload:only")
        confirmed = _fact(student, _degree(institution_original="ADA University"))
        _fact(
            student,
            _degree(institution_original="ADA University", city="Ganja"),
            supersedes=confirmed,
            confirmed=False,
            ref="gap-interview",
        )
        assert pending_changes(student) == []


def test_a_ticked_change_is_confirmed(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ticked")
        _, new = _pending(student)
        assert (
            settle_changes(student=student, shown=[new.id], accepted=[new.id], actor=student)
            == (1, 0)
        )
        new.refresh_from_db()
        assert new.confirmed_by_id == student.id
        assert not has_pending_changes(student)


def test_an_unticked_change_keeps_the_old_value(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "unticked")
        old, new = _pending(student)
        assert (
            settle_changes(student=student, shown=[new.id], accepted=[], actor=student) == (0, 1)
        )
        [tip] = unsuperseded_facts(student).filter(category=EDU)
        assert tip.supersedes_id == new.id
        assert tip.payload == old.payload
        assert tip.source_ref == old.source_ref
        assert tip.confirmed_by_id == student.id
        assert [f.id for f in generatable_facts(student).filter(category=EDU)] == [tip.id]
        assert AuditEvent.objects.filter(event="fact.change_declined", object_id=tip.id).exists()


def test_only_the_changes_shown_are_settled(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stale")
        _, shown = _pending(student)
        other = _fact(
            student,
            _degree(institution_original="Unistra", degree_as_awarded="MSc Chemistry"),
        )
        unseen = _fact(
            student,
            _degree(
                institution_original="Unistra",
                degree_as_awarded="MSc Chemistry",
                city="Strasbourg",
            ),
            supersedes=other,
            confirmed=False,
            ref="upload:third",
        )
        settle_changes(student=student, shown=[shown.id], accepted=[], actor=student)
        assert [c.fact.id for c in pending_changes(student)] == [unseen.id]


def test_settling_twice_changes_nothing_the_second_time(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "twice")
        _, new = _pending(student)
        settle_changes(student=student, shown=[new.id], accepted=[], actor=student)
        count = VerifiedFact.objects.filter(student=student).count()
        assert (
            settle_changes(student=student, shown=[new.id], accepted=[], actor=student) == (0, 0)
        )
        assert VerifiedFact.objects.filter(student=student).count() == count


def test_an_id_that_is_not_a_pending_change_is_ignored(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "forged")
        _pending(student)
        assert (
            settle_changes(student=student, shown=[uuid4()], accepted=[uuid4()], actor=student)
            == (0, 0)
        )
        assert has_pending_changes(student)


def test_a_third_upload_is_shown_against_what_the_student_last_confirmed(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "stacked")
        old, second = _pending(student)
        third = _fact(
            student,
            _degree(end_date=date(2023, 8, 1)),
            supersedes=second,
            confirmed=False,
            ref="upload:third",
        )
        [change] = pending_changes(student)
    assert change.fact.id == third.id and change.kept.id == old.id
