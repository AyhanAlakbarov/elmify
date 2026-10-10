"""Write evidence into the shared ledger.

This is the only module in the package that WRITES to the ledger -- the
property Task 8's structural invariant tests pin
(tests/documents/evidence/test_invariants.py). `intake.py` also imports
Django models (VerifiedFact, DocumentVersion, Membership), but only for type
annotations; it calls no `.objects.` and no `.save()`, which is exempted and
separately checked there. Every other module in this package is pure or
plain HTTP, which is what makes the interesting logic testable without a
database.

Every payload is built by verification.fact_payload -- "the place payload keys
are defined in exactly one place, the place the verifier reads them from". A
hand-built dict here would drift from the verifier and the drift would be
silent.

WHY MECHANICAL FACTS ARE CONFIRMED AT INGEST. ingest_uploaded_cv writes
confirmed_by=None and its docstring explains why: "the anti-fabrication design
collapses if a model's reading of an unverified file can flow into a generated
document." That rule is about a MODEL'S READING. Crossref and the GitHub API
return structured records parsed deterministically with no model in the path,
and every field is re-derivable from the registry at any time. Confirming them
would mean a human re-reading what the parser read. The student supplying the
source is the act of confirmation, so confirmed_by is the student.

Anything extraction.py proposes is the opposite case and is written
confirmed_by=None -- it is not a fact until a human accepts or edits it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from django.utils import timezone

from apps.tenancy.models import Membership

from ..models import VerifiedFact
from ..schemas import PublicationEntry, PublicationStatus, ResearchEntry, SkillEntry
from ..verification import fact_payload
from .extraction import Technique
from .publication import PublicationRecord
from .repo import RepoSnapshot

#: Crossref and OpenAlex types we are willing to record as published. Anything
#: else -- a preprint, posted content, a dataset -- is not guessed at: the
#: schema forbids upgrading unpublished work, so it goes to the student.
_PUBLISHED_TYPES = frozenset(
    {"journal-article", "proceedings-article", "book-chapter", "article"}
)


class UnusablePublication(ValueError):
    """The record cannot be recorded as a publication without a human."""


def publication_entry(record: PublicationRecord) -> PublicationEntry:
    """A registry record as a schema entry.

    self_author_index is deliberately None. Name matching cannot distinguish
    the applicant from a co-author with a similar surname, which is exactly why
    the schema stores an index rather than a name -- and the student picks it.
    """
    if record.work_type not in _PUBLISHED_TYPES:
        raise UnusablePublication(f"unrecognised work type: {record.work_type!r}")
    return PublicationEntry(
        authors=record.authors,
        self_author_index=None,
        title=record.title,
        venue=record.venue,
        year=record.year,
        volume=record.volume,
        issue=record.issue,
        pages=record.pages,
        doi=record.doi,
        status=PublicationStatus.PUBLISHED,
    )


def _previous(student: Membership, source_ref: str, category: str) -> VerifiedFact | None:
    """The unsuperseded fact this one replaces, if the artefact was seen before.

    VerifiedFact is append-only: re-ingesting supersedes rather than
    duplicating, so a student who pastes the same repository twice does not end
    up with two of every skill.
    """
    return (
        VerifiedFact.objects.filter(
            student=student,
            source_ref=source_ref,
            category=category,
            superseded_by__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )


def write_publication_fact(
    *, student: Membership, record: PublicationRecord
) -> VerifiedFact:
    entry = publication_entry(record)
    source_ref = f"doi:{record.doi}"
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.PUBLICATION,
        payload=fact_payload(entry, category=VerifiedFact.Category.PUBLICATION),
        source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        source_ref=source_ref,
        confirmed_by=student,
        confirmed_at=timezone.now(),
        supersedes=_previous(student, source_ref, VerifiedFact.Category.PUBLICATION),
        created_by=student,
    )


#: Below this a language is a stray file, not a skill. The validated
#: repository carried 371 bytes of R (must be excluded) alongside 828 bytes
#: of Shell (must be included) in a Python chemistry project, so the floor
#: has to land above 371 and at or below 828. 500 is a round number inside
#: that window; the exact value beyond that is a judgement call, not derived.
_LANGUAGE_FLOOR_BYTES = 500


@dataclass(frozen=True)
class ProjectDescription:
    """What a project did, once the student has accepted it as his words."""

    thesis_title: str
    methods: str | None
    outcomes: str | None


def _repo_source_ref(snapshot: RepoSnapshot) -> str:
    return f"repo:{snapshot.ref.host}:{snapshot.ref.owner}/{snapshot.ref.name}"


#: A repository can import a long tail; the most-imported head is the story.
#: The rank is intake's per-file import count, not the name -- an alphabetical
#: cut kept `ase` and dropped `torch`.
_MAX_LIBRARY_SKILLS = 15
#: Same reasoning for methods the model reads out of the code.
_MAX_TECHNIQUE_SKILLS = 12

class _Kind(NamedTuple):
    """Everything the kind of a skill name decides."""

    heading: str
    #: Namespaces the source_ref so a library and a language of the same name
    #: supersede their own row and not each other's.
    prefix: str
    tier: str
    confirmed: bool


#: The three kinds of name a skills section holds. They differ in what the
#: name IS:
#:
#:   language  -- a language the host measured in bytes. Mechanical, and the
#:                only kind confirmed without a human: confirming a byte count
#:                would mean re-reading what the API already computed.
#:   library   -- a third-party import, or a dependency the project's own
#:                manifest declares. Mechanical that it is there, interpretive
#:                that it is a skill.
#:   technique -- a named method that exists independently of this project,
#:                read by a model out of the project's prose.
#:
#: One table, not four arguments per call site: a technique written
#: AUTHORITATIVE_DOCUMENT and confirmed would auto-confirm a model's reading.
#: Here that combination cannot be spelled.
#:
#: What is deliberately NOT a skill: anything whose meaning depends on the
#: project it came from. A parameter, a dataset or its size, a metric or a
#: score, a data format, the particular input representation a project chose.
#: The test is transferability -- would the name mean the same thing to
#: someone on an unrelated project in a different field? Those details belong
#: in the project's description, where they describe the work instead of
#: inflating a list. The domain they add up to is a competency the student
#: claims, not one this package derives from a file listing.
_KINDS = {
    "language": _Kind(
        "Languages and tools", "", VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT, True
    ),
    "library": _Kind(
        "Libraries and frameworks", "lib:", VerifiedFact.SourceTier.STUDENT_STATEMENT, False
    ),
    "technique": _Kind(
        "Core competencies", "method:", VerifiedFact.SourceTier.STUDENT_STATEMENT, False
    ),
}


def _import_evidence(count: int) -> str:
    """What backs a library name, in words a student reads on a review screen.

    Count 0 means the manifest declared it and no parsed file imports it --
    which is still worth proposing, just weaker than declared and used.
    """
    if not count:
        return "declared in the project's manifest"
    return f"imported by {count} file{'s' if count != 1 else ''}"


def _write_skills(
    *, student: Membership, snapshot: RepoSnapshot, entries: tuple[tuple[str, str], ...], kind: str
) -> tuple[VerifiedFact, ...]:
    """One skill row per (name, evidence) pair. The kind decides the rest.

    ``kind`` is what a later tailoring pass reads; the heading it maps to is
    only how the name renders, and can be renamed without touching tailoring.
    """
    spec = _KINDS[kind]
    source_ref = _repo_source_ref(snapshot)
    now = timezone.now() if spec.confirmed else None
    return tuple(
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.SKILL,
            payload=fact_payload(
                SkillEntry(name=name, category=spec.heading, kind=kind, evidence=evidence),
                category=VerifiedFact.Category.SKILL,
            ),
            source_tier=spec.tier,
            source_ref=f"{source_ref}#{spec.prefix}{name}",
            confirmed_by=student if spec.confirmed else None,
            confirmed_at=now,
            supersedes=_previous(
                student, f"{source_ref}#{spec.prefix}{name}", VerifiedFact.Category.SKILL
            ),
            created_by=student,
        )
        for name, evidence in entries
    )


def write_skill_facts(
    *, student: Membership, snapshot: RepoSnapshot
) -> tuple[VerifiedFact, ...]:
    """Languages the host measured, as confirmed skill facts.

    A byte count is not an opinion and is re-derivable from the API at any
    time, so this is the AUTHORITATIVE_DOCUMENT tier and needs no human.
    """
    return _write_skills(
        student=student,
        snapshot=snapshot,
        entries=tuple(
            (language, f"{size} bytes")
            for language, size in sorted(snapshot.languages.items())
            if size >= _LANGUAGE_FLOOR_BYTES
        ),
        kind="language",
    )


def write_library_skill_facts(
    *,
    student: Membership,
    snapshot: RepoSnapshot,
    libraries: tuple[tuple[str, int], ...],
) -> tuple[VerifiedFact, ...]:
    """Third-party imports as PROPOSED skills, for the student to confirm.

    Deliberately weaker than write_skill_facts, which auto-confirms. Two
    reasons, both measured on real repositories:

    * That a file imports `torch` is mechanical; that the student therefore
      *has* PyTorch as a skill is interpretive, and the language byte counts
      at least come from the host's own measurement.
    * An import need not resolve to anything. MicroKatc imports
      `copasi_parser` and contains no such file; cdr_bench imports `cdr`. A
      name that is neither stdlib, nor local, nor installable is not a
      technology, and nothing offline can tell the difference.

    So these are written STUDENT_STATEMENT with confirmed_by=None -- recorded,
    attributed to nobody yet, and his to accept or drop. The same state
    ingest_uploaded_cv writes for a claim read off an unverified CV.
    """
    return _write_skills(
        student=student,
        snapshot=snapshot,
        entries=tuple(
            (name, _import_evidence(count))
            for name, count in sorted(libraries, key=lambda item: (-item[1], item[0]))
        )[:_MAX_LIBRARY_SKILLS],
        kind="library",
    )


def write_technique_skill_facts(
    *, student: Membership, snapshot: RepoSnapshot, techniques: tuple[Technique, ...]
) -> tuple[VerifiedFact, ...]:
    """Named methods the model read out of the project, as PROPOSED skills.

    A technique is transferable: PCA, GTM, UMAP and t-SNE mean the same thing
    on somebody else's project, which is what makes them a skill rather than a
    fact about this repository. The model is asked for exactly that and told
    to leave a project's own features -- a descriptor, a metric, a file format,
    a dataset dimension -- in the description where they belong.

    Unconfirmed, like the libraries: this is the model's reading, so it has no
    author until he gives it one.
    """
    return _write_skills(
        student=student,
        snapshot=snapshot,
        entries=tuple(
            {t.name: (t.name, t.excerpt) for t in techniques}.values()
        )[:_MAX_TECHNIQUE_SKILLS],
        kind="technique",
    )


def write_project_fact(
    *, student: Membership, snapshot: RepoSnapshot, description: ProjectDescription
) -> VerifiedFact:
    """A project the student has described in his own words.

    STUDENT_STATEMENT, not AUTHORITATIVE_DOCUMENT: the repository proves the
    code exists and who committed to it, never what it achieved. Dates come
    from the repository's commit range (the last 100 commits fetched, not
    necessarily the student's own -- see repo.py's fetch_repo), not from
    memory.
    """
    entry = ResearchEntry(
        thesis_title=description.thesis_title,
        institution=None,
        start_date=snapshot.first_commit.date() if snapshot.first_commit else None,
        end_date=snapshot.last_commit.date() if snapshot.last_commit else None,
        methods=description.methods,
        outcomes=description.outcomes,
    )
    source_ref = _repo_source_ref(snapshot)
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.RESEARCH,
        payload=fact_payload(entry, category=VerifiedFact.Category.RESEARCH),
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref=source_ref,
        confirmed_by=student,
        confirmed_at=timezone.now(),
        supersedes=_previous(student, source_ref, VerifiedFact.Category.RESEARCH),
        created_by=student,
    )
