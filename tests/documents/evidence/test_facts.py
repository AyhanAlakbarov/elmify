from datetime import datetime

import pytest

from apps.documents.evidence.extraction import Technique
from apps.documents.evidence.facts import (
    ProjectDescription,
    UnusablePublication,
    publication_entry,
    write_project_fact,
    write_publication_fact,
    write_skill_facts,
)
from apps.documents.evidence.publication import PublicationRecord
from apps.documents.evidence.repo import RepoSnapshot
from apps.documents.evidence.sources import RepoRef
from apps.documents.models import VerifiedFact
from apps.documents.schemas import PublicationStatus
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _record(**overrides):
    base = dict(
        doi="10.1021/acscatal.5c00348",
        title="Microkinetic Assessment of Ligand-Exchanging Catalytic Cycles",
        venue="ACS Catalysis",
        year=2025,
        volume="15",
        issue="6",
        pages="4739-4745",
        authors=("Orkhan Abdullayev", "Diego Garay-Ruiz", "Berta Bori-Bru", "Carles Bo"),
        work_type="journal-article",
    )
    base.update(overrides)
    return PublicationRecord(**base)


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def test_a_record_becomes_a_publication_entry_with_no_self_author_index():
    """Which author the applicant is, is his call. Name matching cannot tell
    'Abdullayev O.' from a co-author's similar surname, so the index is left
    null and he selects it."""
    entry = publication_entry(_record())
    assert entry.title.startswith("Microkinetic Assessment")
    assert entry.authors[0] == "Orkhan Abdullayev"
    assert len(entry.authors) == 4
    assert entry.self_author_index is None
    assert entry.doi == "10.1021/acscatal.5c00348"
    assert entry.status == PublicationStatus.PUBLISHED


def test_the_locator_survives_all_the_way_into_the_fact_payload(
    agency_a, django_user_model
):
    """The gap this closes. publication.py fetched issue "6" from Crossref and
    PublicationEntry had nowhere to put it, so fact_payload dropped it between
    the registry and the ledger -- a fetched-then-discarded field, invisible to
    every test that stopped at PublicationRecord. The CV this was validated
    against prints that issue number as "XXX"."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-locator")
        fact = write_publication_fact(student=student, record=_record())
        assert fact.payload["volume"] == "15"
        assert fact.payload["issue"] == "6"
        assert fact.payload["pages"] == "4739-4745"


def test_an_unpublished_work_type_is_refused_rather_than_upgraded():
    """The schema forbids upgrading unpublished work to PUBLISHED. A type we
    do not recognise as published is not guessed at -- it needs the student."""
    with pytest.raises(UnusablePublication):
        publication_entry(_record(work_type="posted-content"))


def test_writing_the_fact_stamps_provenance_and_auto_confirms(agency_a, django_user_model):
    """Crossref is an external registry parsed deterministically -- no model in
    the path -- so the fact is confirmed at ingest. See the module docstring."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-1")
        fact = write_publication_fact(student=student, record=_record())
        assert fact.category == VerifiedFact.Category.PUBLICATION
        assert fact.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
        assert fact.source_ref == "doi:10.1021/acscatal.5c00348"
        assert fact.confirmed_by_id == student.id
        assert fact.confirmed_at is not None
        assert fact.created_by_id == student.id


def test_the_payload_comes_from_the_canonical_builder(agency_a, django_user_model):
    """fact_payload is the one place payload keys are defined -- the place the
    verifier reads them from. A hand-built dict would drift."""
    from apps.documents.verification import fact_payload

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-2")
        record = _record()
        fact = write_publication_fact(student=student, record=record)
        assert fact.payload == fact_payload(
            publication_entry(record), category=VerifiedFact.Category.PUBLICATION
        )


def test_re_ingesting_the_same_doi_supersedes_rather_than_duplicates(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-3")
        first = write_publication_fact(student=student, record=_record())
        second = write_publication_fact(student=student, record=_record(year=2026))
        assert second.supersedes_id == first.id
        assert VerifiedFact.objects.filter(source_ref=first.source_ref).count() == 2


def _snapshot(**overrides):
    base = dict(
        ref=RepoRef("github", "0rkhann", "MicroKatc"),
        description="Quantitative assessment of catalytic cycles",
        is_fork=False,
        parent=None,
        languages={"Python": 60731, "Shell": 828},
        contributors={"0rkhann": 21},
        commit_count=21,
        first_commit=datetime.fromisoformat("2024-08-28T00:00:00+00:00"),
        last_commit=datetime.fromisoformat("2025-02-22T00:00:00+00:00"),
        ahead_by=None,
        file_names=("main.py", "README.md"),
    )
    base.update(overrides)
    return RepoSnapshot(**base)


def test_languages_become_confirmed_skill_facts(agency_a, django_user_model):
    """A byte count is not an opinion. The host computed it and it is
    re-derivable, so confirming it would mean re-reading what we read."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-4")
        facts = write_skill_facts(student=student, snapshot=_snapshot())
        names = {fact.payload["name"] for fact in facts}
        assert names == {"Python", "Shell"}
        for fact in facts:
            assert fact.category == VerifiedFact.Category.SKILL
            assert fact.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
            # One ref per language, so re-ingesting supersedes per skill
            # rather than leaving two Pythons in the ledger.
            assert fact.source_ref.startswith("repo:github:0rkhann/MicroKatc#")
            assert fact.confirmed_by_id == student.id


def test_a_language_below_the_noise_floor_is_not_a_skill(agency_a, django_user_model):
    """371 bytes of R in a chemistry repo is a stray file, not a skill. The
    validated repository had exactly that."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-5")
        facts = write_skill_facts(
            student=student,
            snapshot=_snapshot(languages={"Python": 60731, "R": 371}),
        )
        assert {fact.payload["name"] for fact in facts} == {"Python"}


def test_an_accepted_description_becomes_the_students_own_claim(
    agency_a, django_user_model
):
    """The LLM proposes; he authors. A description reaches the ledger only
    once he has accepted or edited it, and then it is his statement."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-6")
        fact = write_project_fact(
            student=student,
            snapshot=_snapshot(),
            description=ProjectDescription(
                thesis_title="MicroKatc — automated microkinetic analysis",
                methods="Gaussian DFT output to COPASI microkinetic simulation.",
                outcomes="Apparent activation energies by Arrhenius linearisation.",
            ),
        )
        assert fact.category == VerifiedFact.Category.RESEARCH
        assert fact.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT
        assert fact.confirmed_by_id == student.id
        assert fact.payload["thesis_title"].startswith("MicroKatc")


def test_the_project_fact_carries_the_commit_range_as_its_dates(
    agency_a, django_user_model
):
    """His CV claims Jul-Aug 2024; the commits run to Feb 2025. The dates come
    from the repository, not from memory."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-7")
        fact = write_project_fact(
            student=student,
            snapshot=_snapshot(),
            description=ProjectDescription("MicroKatc", None, None),
        )
        assert fact.payload["start_date"] == "2024-08-28"
        assert fact.payload["end_date"] == "2025-02-22"


def test_reingesting_the_same_repo_chains_supersedes_per_language(
    agency_a, django_user_model
):
    """The source_ref for each row is built twice -- once to create it, once
    in _previous's lookup -- so a drift between the two would silently
    duplicate rather than chain. Only a live re-ingest catches that."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-8")
        first = write_skill_facts(student=student, snapshot=_snapshot())
        second = write_skill_facts(
            student=student,
            snapshot=_snapshot(languages={"Python": 70000, "Shell": 900}),
        )
        first_by_name = {fact.payload["name"]: fact for fact in first}
        second_by_name = {fact.payload["name"]: fact for fact in second}
        assert second_by_name["Python"].supersedes_id == first_by_name["Python"].id
        assert second_by_name["Shell"].supersedes_id == first_by_name["Shell"].id
        # Neither language's chain crosses into the other's.
        assert second_by_name["Python"].supersedes_id != first_by_name["Shell"].id
        assert second_by_name["Shell"].supersedes_id != first_by_name["Python"].id


def test_reingesting_the_same_repo_chains_the_project_fact(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-9")
        first = write_project_fact(
            student=student,
            snapshot=_snapshot(),
            description=ProjectDescription("MicroKatc", None, None),
        )
        second = write_project_fact(
            student=student,
            snapshot=_snapshot(),
            description=ProjectDescription("MicroKatc v2", None, None),
        )
        assert second.supersedes_id == first.id


def test_library_skills_are_proposed_not_confirmed(agency_a, django_user_model):
    """A language byte count is the host's own measurement; an import is not.
    MicroKatc imports `copasi_parser` and contains no such file, so a library
    name can be a technology that does not exist. These are recorded with no
    author until he accepts them."""
    from apps.documents.evidence.facts import write_library_skill_facts

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-libs")
        facts = write_library_skill_facts(
            student=student,
            snapshot=_snapshot(),
            libraries=(("torch", 4), ("rdkit", 2), ("copasi_parser", 1)),
        )
        assert {f.payload["name"] for f in facts} == {"torch", "rdkit", "copasi_parser"}
        for fact in facts:
            assert fact.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT
            assert fact.confirmed_by_id is None
            assert fact.confirmed_at is None
            # "lib:" keeps a library from colliding with a language of the
            # same name, so re-ingest supersedes the right row.
            assert "#lib:" in fact.source_ref


def test_the_three_skill_headings_are_kept_apart(agency_a, django_user_model):
    """A skills section has three different kinds of name in it, and they are
    not interchangeable: a language the host measured, a library parsed from
    an import, and a transferable method read out of the prose. Project
    features -- MACCS keys, Tanimoto, HDF5, '1024 to 2 components' -- are none
    of these and never become skills at all."""
    from apps.documents.evidence.facts import (
        write_library_skill_facts,
        write_technique_skill_facts,
    )

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-headings")
        snapshot = _snapshot()
        languages = write_skill_facts(student=student, snapshot=snapshot)
        libraries = write_library_skill_facts(
            student=student, snapshot=snapshot, libraries=(("rdkit", 2), ("torch", 1))
        )
        techniques = write_technique_skill_facts(
            student=student, snapshot=snapshot, techniques=(
                Technique(name="PCA", excerpt="reduced with PCA"),
                Technique(name="UMAP", excerpt="UMAP embedding of the set"),
                Technique(name="t-SNE", excerpt="t-SNE for the 2-D map"),
            )
        )

        assert {f.payload["category"] for f in languages} == {"Languages and tools"}
        assert {f.payload["category"] for f in libraries} == {"Libraries and frameworks"}
        assert {f.payload["category"] for f in techniques} == {"Core competencies"}

        # Only the host's own byte counts are auto-confirmed.
        assert all(f.confirmed_by_id == student.id for f in languages)
        assert all(f.confirmed_by_id is None for f in libraries + techniques)

        # A library and a language of the same name occupy different rows.
        refs = {f.source_ref for f in languages + libraries + techniques}
        assert len(refs) == len(languages + libraries + techniques)
        assert any(r.endswith("#Python") for r in refs)
        assert any(r.endswith("#lib:torch") for r in refs)
        assert any(r.endswith("#method:PCA") for r in refs)


def test_a_duplicated_technique_is_written_once(agency_a, django_user_model):
    from apps.documents.evidence.facts import write_technique_skill_facts

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-dupe")
        facts = write_technique_skill_facts(
            student=student, snapshot=_snapshot(), techniques=(
                Technique(name="PCA", excerpt="first mention of PCA"),
                Technique(name="PCA", excerpt="second mention of PCA"),
                Technique(name="UMAP", excerpt="UMAP embedding"),
            )
        )
        assert [f.payload["name"] for f in facts] == ["PCA", "UMAP"]


def test_the_library_cut_keeps_the_most_imported_not_the_alphabetically_first(
    agency_a, django_user_model
):
    """`ase` beat `torch` only because the truncation sorted by name."""
    from apps.documents.evidence.facts import write_library_skill_facts

    libraries = tuple((f"pkg{index:02d}", 1) for index in range(20)) + (("torch", 9),)

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-rank")
        facts = write_library_skill_facts(
            student=student, snapshot=_snapshot(), libraries=libraries
        )

    names = [fact.payload["name"] for fact in facts]
    assert len(names) == 15
    assert names[0] == "torch"


def test_each_skill_row_records_what_backs_it(agency_a, django_user_model):
    """Every kind of skill name carries a different kind of evidence, and the
    row says which. A byte count is the host's measurement, an import count is
    ours, and a manifest declaration is the project's own statement."""
    from apps.documents.evidence.facts import (
        write_library_skill_facts,
        write_technique_skill_facts,
    )

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ev-evidence")
        snapshot = _snapshot()
        languages = write_skill_facts(student=student, snapshot=snapshot)
        libraries = write_library_skill_facts(
            student=student,
            snapshot=snapshot,
            libraries=(("torch", 9), ("ase", 1), ("d3", 0)),
        )
        techniques = write_technique_skill_facts(
            student=student,
            snapshot=snapshot,
            techniques=(Technique(name="PCA", excerpt="reduced with PCA"),),
        )

    assert {f.payload["kind"] for f in languages} == {"language"}
    assert {f.payload["name"]: f.payload["evidence"] for f in languages}["Python"] == (
        "60731 bytes"
    )

    assert {f.payload["kind"] for f in libraries} == {"library"}
    evidence = {f.payload["name"]: f.payload["evidence"] for f in libraries}
    assert evidence["torch"] == "imported by 9 files"
    # Singular, because "imported by 1 files" is read by a student.
    assert evidence["ase"] == "imported by 1 file"
    assert evidence["d3"] == "declared in the project's manifest"

    assert {f.payload["kind"] for f in techniques} == {"technique"}
