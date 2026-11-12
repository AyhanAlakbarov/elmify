import pytest

from apps.accounts.models import StudentProfileVersion
from apps.documents.models import VerifiedFact
from apps.documents.profile_bridge import bridge_profile_to_facts
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _record(institution="Example University", qualification="BSc", grade="1.7"):
    return {
        "institution": institution,
        "country_code": "DE",
        "qualification": qualification,
        "field": "Computer Science",
        "grade": grade,
        "grading_scale": "German 1.0-5.0",
        "completed_on": "2024-06-30",
    }


def _language(language="German", level="C1"):
    return {
        "language": language,
        "level": level,
        "evidence_type": "TEST",
        "available_by": "2026-01-01",
    }


def _snapshot(*, records=None, languages=None):
    return {
        "schema_version": 3,
        "nationality": "DE",
        "country_of_residence": "DE",
        "academic_history": records if records is not None else [_record()],
        "target_field": "Computer Science",
        "intended_intake": "2027-09-01",
        "acceptable_teaching_languages": ["English"],
        "language_evidence": languages if languages is not None else [],
        "experience": [],
        "research_interests": [],
        "career_intent": "PHD",
        "date_of_birth": "2000-01-01",
        "application_budget": {"amount": "10000.00", "currency": "EUR"},
        "funding_dependency": "IMPORTANT",
        "self_funding_capacity": {"amount": "10000", "currency": "EUR"},
        "strategy": "BALANCED",
        "duration_preference": "TWO_YEAR",
        "duration_flexibility": "WEIGHTED",
        "allowed_countries": [],
        "excluded_countries": [],
        "mobility_priorities": [],
        "non_negotiables": [],
        "negotiable_preferences": [],
        "weights": {},
    }


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _profile(student, snapshot, version):
    return StudentProfileVersion.objects.create(
        student=student, version=version, schema_version=3, snapshot=snapshot
    )


def test_bridge_creates_unconfirmed_student_statement_facts(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b1")
        _profile(student, _snapshot(languages=[_language()]), 1)
        facts = bridge_profile_to_facts(student)
        assert len(facts) == 2
        assert all(fact.confirmed_by is None for fact in facts)
        assert all(
            fact.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT for fact in facts
        )
        assert {fact.category for fact in facts} == {
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.LANGUAGE,
        }


def test_bridge_is_idempotent_on_an_unchanged_profile(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b2")
        _profile(student, _snapshot(languages=[_language()]), 1)
        bridge_profile_to_facts(student)
        assert bridge_profile_to_facts(student) == ()
        assert VerifiedFact.objects.filter(student=student).count() == 2


def test_bridge_supersedes_only_the_record_that_changed(agency_a, django_user_model):
    """Two entries, one edited: the other must be left completely alone."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b3")
        first = _record(institution="First University", qualification="BA")
        second = _record(institution="Second University", qualification="BSc")
        _profile(student, _snapshot(records=[first, second]), 1)
        created = bridge_profile_to_facts(student)
        assert len(created) == 2

        edited = {**second, "grade": "1.3"}
        _profile(student, _snapshot(records=[first, edited]), 2)
        second_run = bridge_profile_to_facts(student)

        assert len(second_run) == 1
        assert second_run[0].payload["institution_original"] == "Second University"
        assert second_run[0].supersedes_id == created[1].id
        # the untouched record is still a chain tip
        created[0].refresh_from_db()
        assert not VerifiedFact.objects.filter(supersedes=created[0]).exists()


def test_bridge_supersedes_a_changed_language_entry(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b4")
        _profile(student, _snapshot(languages=[_language(level="B2")]), 1)
        created = bridge_profile_to_facts(student)
        _profile(student, _snapshot(languages=[_language(level="C1")]), 2)
        second_run = bridge_profile_to_facts(student)
        assert len(second_run) == 1
        assert second_run[0].category == VerifiedFact.Category.LANGUAGE
        assert second_run[0].payload["cefr_level"] == "C1"
        language_fact = next(
            fact for fact in created if fact.category == VerifiedFact.Category.LANGUAGE
        )
        assert second_run[0].supersedes_id == language_fact.id


def test_bridge_with_no_profile_is_a_no_op(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b5")
        assert bridge_profile_to_facts(student) == ()


def test_bridged_facts_are_invisible_to_generation(agency_a, django_user_model):
    from apps.documents.verification import generatable_facts

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b6")
        _profile(student, _snapshot(), 1)
        bridge_profile_to_facts(student)
        assert list(generatable_facts(student)) == []


def test_finalize_consultation_bridges_profile_records_to_ledger(agency_a, django_user_model):
    from apps.accounts.consultation import ConsultationDraft, finalize_consultation
    from apps.documents.verification import unsuperseded_facts
    from tests.accounts.test_prefill import _ANSWERS

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b7")
        draft = ConsultationDraft(
            agency_a.id,
            student.id,
            {
                **_ANSWERS,
                "academic_history": [_record()],
                "language_evidence": [_language(language="English")],
            },
        )
        finalize_consultation(membership=student, draft=draft)
        facts = list(unsuperseded_facts(student))
        assert {f.category for f in facts} == {
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.LANGUAGE,
        }
        edu_fact = next(f for f in facts if f.category == VerifiedFact.Category.EDUCATION)
        assert edu_fact.payload["institution_original"] == "Example University"
        assert edu_fact.payload["end_date"] == "2024-06-30"


def test_sync_facts_to_profile_updates_language_evidence_and_degree_grade(
    agency_a, django_user_model
):
    from django.utils import timezone

    from apps.documents.profile_bridge import sync_facts_to_profile

    now = timezone.now()
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b8")
        _profile(
            student,
            _snapshot(
                records=[_record(grade="not stated")],
                languages=[],
            ),
            1,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.LANGUAGE,
            payload={
                "test_name": "IELTS Academic",
                "language": "English",
                "test_score": "7.5",
                "cefr_level": "C1",
                "test_date": "2026-03-15",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:11111111-1111-1111-1111-111111111111",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={
                "institution_original": "Example University",
                "degree_as_awarded": "BSc",
                "country": "DE",
                "end_date": "2024-06-30",
                "grade_native": "1.3",
                "grade_scale": "German 1.0-5.0",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="gap_interview",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )

        updated = sync_facts_to_profile(student)
        assert updated is not None
        assert updated.version == 2
        assert updated.snapshot["academic_history"][0]["grade"] == "1.3"
        assert updated.snapshot["language_evidence"] == [
            {
                "language": "English",
                "level": "C1",
                "evidence_type": "TEST",
                "available_by": "2026-03-15",
            }
        ]
        # Second call with no changes is a no-op
        assert sync_facts_to_profile(student) is None

        # A subsequent test-score fact with cefr_level=None preserves the existing CEFR code
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.LANGUAGE,
            payload={
                "test_name": "TOEFL iBT",
                "language": "English",
                "test_score": "110",
                "cefr_level": None,
                "test_date": "2026-04-01",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:22222222-2222-2222-2222-222222222222",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        updated_v3 = sync_facts_to_profile(student)
        assert updated_v3 is not None
        assert updated_v3.snapshot["language_evidence"][0]["level"] == "C1"
        assert updated_v3.snapshot["language_evidence"][0]["evidence_type"] == "TEST"
        assert updated_v3.snapshot["language_evidence"][0]["available_by"] == "2026-04-01"


def test_pick_higher_language_level_is_monotonic_across_cefr_and_test_scores():
    from apps.documents.profile_bridge import pick_higher_language_level

    assert pick_higher_language_level("B2", "C1") == "C1"
    assert pick_higher_language_level("C1", "B2") == "C1"
    assert (
        pick_higher_language_level("IELTS Academic 6.5", "IELTS Academic 7.5")
        == "IELTS Academic 7.5"
    )
    assert (
        pick_higher_language_level("IELTS Academic 7.5", "IELTS Academic 6.5")
        == "IELTS Academic 7.5"
    )
    assert pick_higher_language_level("TOEFL iBT 95", "TOEFL iBT 108") == "TOEFL iBT 108"


def test_sync_facts_to_profile_never_downgrades_and_enqueues_rebuild_pack(
    agency_a, django_user_model, monkeypatch
):
    from django.utils import timezone

    from apps.documents.profile_bridge import sync_facts_to_profile
    from apps.funding.models import RecommendationRun

    enqueued = []
    monkeypatch.setattr(
        "apps.documents.profile_bridge.enqueue_research_message",
        lambda msg: enqueued.append(msg) or True,
    )
    now = timezone.now()
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b_prog")
        v1 = _profile(student, _snapshot(languages=[_language(language="English", level="B2")]), 1)
        run = RecommendationRun.objects.create(
            profile_version=v1, state=RecommendationRun.State.PUBLISHED
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.LANGUAGE,
            payload={
                "test_name": "IELTS Academic",
                "language": "English",
                "test_score": "7.5",
                "cefr_level": "C1",
                "test_date": "2026-05-01",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:33333333-3333-3333-3333-333333333333",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        v2 = sync_facts_to_profile(student)
        assert v2 is not None
        assert v2.snapshot["language_evidence"][0]["level"] == "C1"
        assert len(enqueued) == 1
        assert (enqueued[0].kind, enqueued[0].run_id) == ("rebuild_pack", run.id)

        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.LANGUAGE,
            payload={
                "test_name": "IELTS Academic",
                "language": "English",
                "test_score": "6.0",
                "cefr_level": "B2",
                "test_date": "2026-02-01",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:44444444-4444-4444-4444-444444444444",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        v3 = sync_facts_to_profile(student)
        assert v3 is None


def test_sync_facts_to_profile_preserves_available_by_on_non_cefr_downgrade_and_scales_progress(
    agency_a, django_user_model
):
    from django.utils import timezone

    from apps.accounts.schemas import StudentProfileSnapshot
    from apps.documents.profile_bridge import has_score_progression, sync_facts_to_profile

    now = timezone.now()
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b_scale")
        _profile(
            student,
            _snapshot(
                languages=[
                    {
                        **_language(language="English", level="IELTS Academic 7.5"),
                        "available_by": "2026-05-01",
                    }
                ]
            ),
            1,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.LANGUAGE,
            payload={
                "test_name": "IELTS Academic",
                "language": "English",
                "test_score": "6.0",
                "test_date": "2026-02-01",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:55555555-5555-5555-5555-555555555555",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        assert sync_facts_to_profile(student) is None

    def _validated(records):
        raw = {k: v for k, v in _snapshot(records=records).items() if k != "weights"}
        return StudentProfileSnapshot.model_validate(raw)

    # Swiss 1.0-6.0 ascending scale (5.2 -> 5.6 is progression, 5.6 -> 5.2 is not)
    swiss_old = _validated([{**_record(grade="5.2"), "grading_scale": "1.0-6.0"}])
    swiss_new = _validated([{**_record(grade="5.6"), "grading_scale": "1.0-6.0"}])
    assert has_score_progression(swiss_old, swiss_new) is True
    assert has_score_progression(swiss_new, swiss_old) is False

    # UK honours progression (2:2 -> 2:1 -> First Class)
    uk_22 = _validated([{**_record(grade="2:2"), "grading_scale": "UK Honours"}])
    uk_21 = _validated([{**_record(grade="2:1"), "grading_scale": "UK Honours"}])
    uk_1st = _validated([{**_record(grade="First Class"), "grading_scale": "UK Honours"}])
    assert has_score_progression(uk_22, uk_21) is True
    assert has_score_progression(uk_21, uk_1st) is True
    assert has_score_progression(uk_1st, uk_21) is False


def test_sync_facts_to_profile_propagates_confirmed_experience_and_research_facts(
    agency_a, django_user_model, monkeypatch
):
    from django.utils import timezone

    from apps.documents.profile_bridge import sync_facts_to_profile
    from apps.funding.models import RecommendationRun

    enqueued = []
    monkeypatch.setattr(
        "apps.documents.profile_bridge.enqueue_research_message",
        lambda msg: enqueued.append(msg) or True,
    )
    now = timezone.now()
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b_exp")
        v1 = _profile(student, _snapshot(), 1)
        run = RecommendationRun.objects.create(
            profile_version=v1, state=RecommendationRun.State.PUBLISHED
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={
                "title": "Data Analyst",
                "employer": "SOCAR",
                "start_date": "2024-03",
                "end_date": "2026-03",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv:exp1",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.RESEARCH,
            payload={
                "thesis_title": "Catalytic Cracking Kinetics",
                "institution": "BSU",
                "start_date": "2023-09",
                "end_date": "2024-06",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv:res1",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        v2 = sync_facts_to_profile(student)
        assert v2 is not None
        assert [(e["kind"], e["months"]) for e in v2.snapshot["experience"]] == [
            ("WORK", 24),
            ("RESEARCH", 9),
        ]
        assert len(enqueued) == 1
        assert (enqueued[0].kind, enqueued[0].run_id) == ("rebuild_pack", run.id)


def test_undated_and_overlapping_experience_facts_do_not_overcount_months(
    agency_a, django_user_model
):
    from django.utils import timezone

    from apps.documents.profile_bridge import experience_records_from_facts

    now = timezone.now()
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b_exp_overlap")
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={
                "title": "Backend Engineer",
                "employer": "Company A",
                "start_date": "2024-01",
                "end_date": "2025-01",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv:ov1",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={
                "title": "Consultant",
                "employer": "Company B",
                "start_date": "2024-07",
                "end_date": "2025-07",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv:ov2",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={
                "title": "Undated Role",
                "employer": "Company C",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv:ov3",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        records = experience_records_from_facts(student)
    assert [(r.summary, r.months) for r in records] == [
        ("Backend Engineer at Company A", 12),
        ("Consultant at Company B", 6),
        ("Undated Role at Company C", 0),
    ]
    assert sum(r.months for r in records if r.kind == "WORK") == 18


def test_attested_c1_not_upgraded_to_test_c1_by_b2_exam_and_all_test_types_rank(
    agency_a, django_user_model
):
    from django.utils import timezone

    from apps.documents.profile_bridge import (
        _language_level_rank,
        pick_higher_language_level,
        sync_facts_to_profile,
    )

    # PTE, Duolingo, TestDaF, DSH, and Cambridge CAE/CPE rank above B2
    assert pick_higher_language_level("B2", "PTE Academic 76") == "PTE Academic 76"
    assert pick_higher_language_level("B2", "Duolingo 135") == "Duolingo 135"
    assert pick_higher_language_level("B1", "TestDaF TDN 4") == "TestDaF TDN 4"
    assert pick_higher_language_level("B1", "DSH-2") == "DSH-2"
    assert _language_level_rank("Native")[0] == 6

    now = timezone.now()
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "b_auth_rank")
        _profile(
            student,
            _snapshot(
                languages=[
                    {
                        "language": "English",
                        "level": "C1",
                        "evidence_type": "ATTESTED",
                        "available_by": "2026-01-01",
                    }
                ]
            ),
            1,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.LANGUAGE,
            payload={
                "test_name": "IELTS Academic",
                "language": "English",
                "test_score": "6.0",
                "cefr_level": None,
                "test_date": "2026-03-15",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:66666666-6666-6666-6666-666666666666",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        updated = sync_facts_to_profile(student)
        assert updated is not None
        assert updated.snapshot["language_evidence"] == [
            {
                "language": "English",
                "level": "IELTS Academic 6.0",
                "evidence_type": "TEST",
                "available_by": "2026-03-15",
            }
        ]




