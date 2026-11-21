"""facts.py: the package's only database access."""

from __future__ import annotations

import pytest
from django.utils import timezone
from pydantic import ValidationError

from apps.concierge.models import DocumentVersion
from apps.documents.evidence import facts
from apps.documents.evidence.extraction import Technique
from apps.documents.evidence.facts import (
    SkillSuggestion,
    UnusablePublication,
    publication_entry,
    suggestions,
    write_publication_fact,
)
from apps.documents.evidence.publication import PublicationRecord
from apps.documents.models import EvidenceReading, VerifiedFact
from apps.documents.schemas import PublicationStatus
from apps.documents.verification import fact_payload, generatable_facts, unsuperseded_facts
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db
WHEN = timezone.now()


def _record(**overrides):
    base = dict(
        doi="10.1021/acscatal.5c00348",
        title="Microkinetic Assessment of Ligand-Exchanging Catalytic Cycles",
        venue="ACS Catalysis", year=2025, volume="15", issue="6", pages="4739-4745",
        authors=("Orkhan Abdullayev", "Diego Garay-Ruiz", "Berta Bori-Bru", "Carles Bo"),
        work_type="journal-article",
    )
    base.update(overrides)
    return PublicationRecord(**base)


@pytest.fixture
def student(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="facts-student")
        member = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
    with tenant_scope(agency_a.id):
        yield member


def _identity(student, payload, *, confirmed):
    return VerifiedFact.objects.create(
        student=student, category=VerifiedFact.Category.IDENTITY, payload=payload,
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:cv",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None, created_by=student,
    )


def _upload(student, kind="THESIS_OR_REPORT", *, state="AVAILABLE", retired=False):
    return DocumentVersion.objects.create(
        tenant_id=student.tenant_id, student=student, object_key="quarantine/x", kind=kind,
        state=state, retired_at=timezone.now() if retired else None,
    )


def _save(student, repo="0rkhann/MicroKatc", skills=(), **reading):
    facts.save_reading(student, source_kind="github", repo=repo, changed_at=WHEN,
                       reader_version=1, reading={"summary": "s", **reading}, skills=skills)


def _skills(student):
    return list(unsuperseded_facts(student).filter(category=VerifiedFact.Category.SKILL))


# --- publications (unchanged behaviour) -------------------------------------------


def test_a_record_becomes_a_publication_entry_with_no_self_author_index():
    entry = publication_entry(_record())
    assert entry.self_author_index is None
    assert entry.status == PublicationStatus.PUBLISHED
    assert entry.issue == "6"


def test_an_unpublished_work_type_is_refused_rather_than_upgraded():
    with pytest.raises(UnusablePublication):
        publication_entry(_record(work_type="posted-content"))


def test_a_publication_is_confirmed_at_ingest_and_supersedes_on_re_ingest(student):
    first = write_publication_fact(student=student, record=_record())
    second = write_publication_fact(student=student, record=_record(year=2026))
    assert first.confirmed_by_id == student.id
    assert first.payload == fact_payload(publication_entry(_record()),
                                         category=VerifiedFact.Category.PUBLICATION)
    assert second.supersedes_id == first.id


# --- skill suggestions -------------------------------------------------------------


def test_suggestions_rank_libraries_floor_languages_and_dedupe_techniques():
    found = suggestions(
        source_ref="repo:github:0rkhann/MicroKatc",
        languages={"Python": 60731, "R": 371},
        libraries=tuple((f"pkg{i:02d}", 1) for i in range(20)) + (("torch", 9), ("d3", 0)),
        techniques=(Technique(name="PCA", excerpt="first PCA"),
                    Technique(name="PCA", excerpt="second PCA"),
                    Technique(name="x" * 101, excerpt="too long a name")),
    )
    by_kind = {kind: [s for s in found if s.kind == kind] for kind in ("language", "library",
                                                                         "technique")}
    assert [s.name for s in by_kind["language"]] == ["Python"]
    assert by_kind["language"][0].evidence == "60731 bytes"
    assert len(by_kind["library"]) == 15 and by_kind["library"][0].name == "torch"
    assert [s.name for s in by_kind["technique"]] == ["PCA"]
    assert by_kind["technique"][0].evidence == "first PCA"
    assert by_kind["technique"][0].source_ref == "repo:github:0rkhann/MicroKatc#method:PCA"
    assert "imported by 1 file" in {s.evidence for s in by_kind["library"]}


def test_a_reading_and_its_suggestions_are_saved_unconfirmed(student):
    _save(student, skills=suggestions(source_ref="repo:github:0rkhann/MicroKatc",
                                      languages={"Python": 6000}, libraries=(("numpy", 2),),
                                      techniques=()))
    [reading] = EvidenceReading.objects.filter(student=student)
    assert (reading.source_kind, reading.repo, reading.reader_version) == (
        "github", "0rkhann/MicroKatc", 1)
    skills = _skills(student)
    assert {s.payload["name"] for s in skills} == {"Python", "numpy"}
    assert all(s.confirmed_by_id is None for s in skills)  # decision 9: languages too
    assert {s.payload["category"] for s in skills} == {"Languages and tools",
                                                       "Libraries and frameworks"}


def test_a_re_read_never_supersedes_a_confirmed_skill(student):
    python = (SkillSuggestion("Python", "language", "6000 bytes",
                              "repo:github:0rkhann/MicroKatc#Python"),)
    _save(student, skills=python)
    [fact] = _skills(student)
    fact.confirmed_by, fact.confirmed_at = student, timezone.now()
    fact.save(update_fields=["confirmed_by", "confirmed_at"])

    _save(student, skills=python)

    [still] = _skills(student)
    assert still.id == fact.id and still.confirmed_by_id == student.id


def test_one_name_across_eight_repos_is_one_suggestion(student):
    for i in range(8):
        _save(student, repo=f"0rkhann/r{i}", skills=(
            SkillSuggestion("numpy", "library", "imported by 1 file",
                            f"repo:github:0rkhann/r{i}#lib:numpy"),))
    assert [s.payload["name"] for s in _skills(student)] == ["numpy"]
    assert EvidenceReading.objects.filter(student=student).count() == 8


def test_a_skill_the_cv_already_lists_is_not_suggested_again(student):
    VerifiedFact.objects.create(
        student=student, category=VerifiedFact.Category.SKILL,
        payload={"name": "python", "category": None, "kind": None, "evidence": None},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:cv",
        created_by=student,
    )
    _save(student, skills=(SkillSuggestion("Python", "language", "6000 bytes", "r#Python"),))
    assert [s.source_ref for s in _skills(student)] == ["upload:cv"]


def test_saving_is_one_step(student):
    """The model call succeeded; then the save raises an error nobody catches. No
    reading and no suggestion survives (spec §14, saving in one step)."""
    bad = (SkillSuggestion("numpy", "library", "imported by 1 file", "r#lib:numpy"),
           SkillSuggestion("x" * 101, "library", "too long for SkillEntry", "r#lib:x"))
    with pytest.raises(ValidationError):
        _save(student, skills=bad)
    assert not EvidenceReading.objects.filter(student=student).exists()
    assert _skills(student) == []


def test_a_re_read_updates_the_one_row_whatever_the_case(student):
    _save(student, repo="0rkhann/MicroKatc", summary="old")
    _save(student, repo="0rkhann/microkatc", summary="new", tree_etag='W/"t1"')
    [reading] = EvidenceReading.objects.filter(student=student)
    assert (reading.repo, reading.reading["summary"]) == ("0rkhann/microkatc", "new")
    assert facts.github_readings(student) == {"0rkhann/microkatc": (WHEN, 1, 'W/"t1"')}
    _save(student, repo="0rkhann/microkatc", summary="no etag")
    assert facts.github_readings(student)["0rkhann/microkatc"][2] == ""


def test_readings_outside_a_complete_discovery_go(student):
    _save(student, repo="0rkhann/Kept")
    _save(student, repo="0rkhann/gone")
    assert facts.delete_github_readings_not_in(student, frozenset({"0rkhann/kept"})) == 1
    assert list(EvidenceReading.objects.values_list("repo", flat=True)) == ["0rkhann/Kept"]
    assert facts.delete_github_reading(student, "0RKHANN/KEPT") == 1


def test_a_discovery_in_githubs_own_spelling_keeps_its_readings(student):
    """refresh.py passes owner/name as GitHub spells them; the comparison is casefolded."""
    _save(student, repo="0rkhann/MicroKatc")
    assert facts.delete_github_readings_not_in(student, frozenset({"0rkhann/MicroKatc"})) == 0
    assert EvidenceReading.objects.filter(student=student).count() == 1


# --- uploads ----------------------------------------------------------------------


def test_reports_to_read_are_live_thesis_uploads_without_a_current_reading(student):
    fresh = _upload(student)
    old_reader = _upload(student)
    current = _upload(student)
    _upload(student, retired=True)
    _upload(student, state="REJECTED_TYPE")
    _upload(student, kind="CV")
    for document, version in ((old_reader, 1), (current, 2)):
        facts.save_reading(student, source_kind="pdf", document=document, changed_at=WHEN,
                           reader_version=version, reading={}, skills=())
    assert facts.reports_to_read(student, reader_version=2) == (fresh, old_reader)


def test_a_retired_uploads_reading_goes(student):
    kept, retired = _upload(student), _upload(student)
    for document in (kept, retired):
        facts.save_reading(student, source_kind="pdf", document=document, changed_at=WHEN,
                           reader_version=1, reading={}, skills=())
    DocumentVersion.objects.filter(id=retired.id).update(retired_at=timezone.now())
    assert facts.delete_retired_report_readings(student) == 1
    assert facts.delete_report_reading(student, kept.id) == 1


def test_latest_cv_is_the_newest_live_cv(student):
    _upload(student, kind="CV")
    newest = _upload(student, kind="CV")
    _upload(student, kind="CV", retired=True)
    assert facts.latest_cv(student) == newest


# --- the GitHub login -------------------------------------------------------------


def test_setting_a_login_supersedes_the_identity_and_inherits_its_confirmation(student):
    tip = _identity(student, {"full_name": "Jane Doe"}, confirmed=True)
    written = facts.set_github_login(student, "0rkhann")
    assert written.supersedes_id == tip.id
    assert written.payload == {"full_name": "Jane Doe", "github_url": "https://github.com/0rkhann",
                               "github_username": "0rkhann"}
    assert written.confirmed_by_id == student.id
    assert written.source_ref == facts.GITHUB_LOGIN_REF
    assert facts.github_login(student) == "0rkhann"


def test_review_focus_4_a_login_never_confirms_what_nobody_confirmed(student):
    """No IDENTITY yet, or only the model's reading of the CV: typing a login must not
    open the generate endpoint's identity gate (api.generate checks exactly this)."""
    facts.set_github_login(student, "0rkhann")
    assert not generatable_facts(student).filter(category=VerifiedFact.Category.IDENTITY).exists()
    _identity(student, {"full_name": "Model Reading"}, confirmed=False)
    facts.set_github_login(student, "other-login")
    assert not generatable_facts(student).filter(category=VerifiedFact.Category.IDENTITY).exists()
    assert facts.github_login(student) == "other-login"


def _document_identity(student, payload):
    """An IDENTITY row read off an identity document (a passport), as the document
    fact reader writes one per field. A typed login must never rewrite it."""
    return VerifiedFact.objects.create(
        student=student, category=VerifiedFact.Category.IDENTITY, payload=payload,
        source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        source_ref="upload:passport:1", confirmed_by=None, confirmed_at=None,
        created_by=student,
    )


def test_a_login_never_supersedes_a_document_identity_row(student):
    named = _identity(student, {"full_name": "Jane Doe"}, confirmed=True)
    passport = _document_identity(student, {"date_of_birth": "2001-02-03"})

    written = facts.set_github_login(student, "0rkhann")

    assert written.supersedes_id == named.id
    assert written.payload["full_name"] == "Jane Doe"
    passport.refresh_from_db()
    assert not VerifiedFact.objects.filter(supersedes=passport).exists()
    assert passport.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
    assert facts.github_login(student) == "0rkhann"

    facts.clear_github_login(student)
    assert not VerifiedFact.objects.filter(supersedes=passport).exists()
    assert facts.github_login(student) == ""


def test_with_only_a_document_identity_the_login_gets_its_own_row(student):
    passport = _document_identity(student, {"date_of_birth": "2001-02-03"})

    first = facts.set_github_login(student, "0rkhann")
    second = facts.set_github_login(student, "other-login")

    assert first.supersedes_id is None and first.source_ref == facts.GITHUB_LOGIN_REF
    assert second.supersedes_id == first.id
    assert not VerifiedFact.objects.filter(supersedes=passport).exists()
    assert facts.github_login(student) == "other-login"


def test_an_unconfirmed_cv_profile_link_is_read(student):
    _identity(student, {"full_name": "Jane", "github_url": "https://github.com/0rkhann"},
              confirmed=False)
    assert facts.github_login(student) == "0rkhann"


def test_clearing_removes_the_login_and_every_github_reading_but_keeps_skills(student):
    _identity(student, {"full_name": "Jane", "github_url": "https://github.com/0rkhann"},
              confirmed=True)
    _save(student, skills=(SkillSuggestion("Python", "language", "6000 bytes", "r#Python"),))
    thesis = _upload(student)
    facts.save_reading(student, source_kind="pdf", document=thesis, changed_at=WHEN,
                       reader_version=1, reading={}, skills=())

    assert facts.clear_github_login(student) == 1

    assert facts.github_login(student) == ""
    assert list(EvidenceReading.objects.values_list("source_kind", flat=True)) == ["pdf"]
    assert [s.payload["name"] for s in _skills(student)] == ["Python"]


def test_nothing_picks_a_reading_up_by_accident(student):
    """Spec §14: a saved reading appears in none of generatable_facts, the confirm list
    (api.fact_candidates' query), tailoring.fact_pool or the portal profile."""
    from apps.documents.tailoring import fact_pool
    from apps.portals.profile import verified_values

    _identity(student, {"full_name": "Jane Doe"}, confirmed=True)
    marker = "MARKER-READING-7731"
    _save(student, summary=marker, bullets=[{"text": marker, "evidence": [marker],
                                             "verdict": "supported"}])
    surfaces = (
        list(generatable_facts(student).values_list("payload", flat=True)),
        list(unsuperseded_facts(student).filter(confirmed_by__isnull=True)
             .values_list("payload", flat=True)),
        fact_pool(student),
        verified_values(student),
    )
    for surface in surfaces:
        assert marker not in repr(surface)
