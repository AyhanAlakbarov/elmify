"""One student declaration, one artefact, one structured outcome.

Nothing here runs speculatively: the entry point is a student saying "I have a
project that is not on my CV" and naming one thing.

THREE OUTCOMES, NOT TWO. NEEDS_INPUT is not a soft failure -- the fetch worked
and the evidence simply cannot support a claim on its own. A fork with no
commits by the student is the canonical case, and collapsing it into either
SUCCESS or FAILED is what puts fabricated projects on a CV.

This function ASKS NOBODY. IntakeResult.question carries what to put to the
student and the facts that frame it; rendering that question, and taking his
answer back, belongs to the consultant surfaces. Nothing in this package
imports a view, a form or a template.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import cast

from openai import OpenAI

from apps.concierge.documents import ReadableObjectStore, open_document
from apps.concierge.models import DocumentVersion
from apps.ratelimit import rate_limited
from apps.research.extraction import ResponsesAPI
from apps.tenancy.models import Membership

from ..ingestion import extract_text
from ..models import VerifiedFact
from .extraction import SIGNAL_FILES, ProposedDescription, propose_description
from .facts import (
    UnusablePublication,
    write_library_skill_facts,
    write_publication_fact,
    write_skill_facts,
    write_technique_skill_facts,
)
from .publication import PublicationNotFound, fetch_publication
from .repo import (
    Authorship,
    RepoNotAccessible,
    RepoSnapshot,
    authorship,
    fetch_file,
    fetch_repo,
)
from .signals import (
    MANIFEST_FILES,
    directory_names,
    file_signals,
    interesting_paths,
    local_module_names,
    manifest_libraries,
)
from .sources import DoiRef, RepoRef, UnsupportedSource, parse_source
from .transport import Transport

#: A model reading a repository does not need the whole repository.
_MAX_EVIDENCE_CHARS = 24_000
#: A model reading a thesis does. The CV default (ingestion._MAX_TEXT_CHARS,
#: 40,000) is right for a CV and wrong here: a real M2 report was cut at
#: exactly that and the student was asked to accept a description of a
#: document the model had read a third of. A master's thesis runs to roughly
#: 150,000-300,000 characters, so this reads a whole one, and _document says
#: so when it does not. The ceiling is deliberately still a ceiling -- it is
#: the cost limiter on a per-student paid call, bounded again by
#: _INTAKE_RATE_LIMIT below.
_MAX_DOCUMENT_CHARS = 200_000
#: Each parsed file is one extra HTTP request, so this is the cost dial of
#: the whole ladder. Twelve shallow files characterise a project; a
#: hundred is a crawl.
_MAX_PARSED_FILES = 12
_MAX_DEFINITIONS_PER_FILE = 20
_MAX_MARKDOWN_CELLS = 12
_MAX_DIRECTORIES = 40

#: A considered action on a real artefact, not a chat turn. Generous for a
#: student working through his projects, a hard ceiling for anything else.
_INTAKE_RATE_LIMIT = 20
_INTAKE_RATE_WINDOW_SECONDS = 3600


class EvidenceRateLimited(RuntimeError):
    """Too many intake attempts for one student in the window."""


class Outcome(Enum):
    SUCCESS = "SUCCESS"
    NEEDS_INPUT = "NEEDS_INPUT"
    FAILED = "FAILED"


@dataclass(frozen=True)
class IntakeResult:
    outcome: Outcome
    facts: tuple[VerifiedFact, ...] = ()
    question: str | None = None
    proposal: ProposedDescription | None = None
    reason: str | None = None


def _publication(
    student: Membership, ref: DoiRef, transport: Transport | None
) -> IntakeResult:
    try:
        record = fetch_publication(ref, transport=transport)
    except PublicationNotFound:
        return IntakeResult(
            outcome=Outcome.NEEDS_INPUT,
            question=(
                f"We could not find {ref.doi} in Crossref or OpenAlex. "
                "Can you give the full citation as it appears in the journal?"
            ),
        )
    try:
        fact = write_publication_fact(student=student, record=record)
    except UnusablePublication as error:
        return IntakeResult(
            outcome=Outcome.NEEDS_INPUT,
            question=(
                f"{record.title} is registered as {record.work_type!r}. "
                "Is it published, in press, under review, or in preparation?"
            ),
            reason=str(error),
        )
    byline = ", ".join(record.authors)
    return IntakeResult(
        outcome=Outcome.SUCCESS,
        facts=(fact,),
        # Never matched automatically: "Abdullayev O." and a co-author's
        # similar surname are indistinguishable by name.
        question=f"Which of these authors are you? {byline}",
    )


def _repository(
    student: Membership,
    ref: RepoRef,
    *,
    owner_login: str,
    token: str | None,
    transport: Transport | None,
    client: object | None = None,
) -> IntakeResult:
    try:
        snapshot = fetch_repo(
            ref, owner_login=owner_login, token=token, transport=transport
        )
    except RepoNotAccessible as error:
        return IntakeResult(outcome=Outcome.FAILED, reason=str(error))

    # WHAT THE AUTHORSHIP GATE DOES, AND WHAT IT MUST NOT DO. It decides
    # whether we may write an auto-confirmed MECHANICAL fact in his name. It
    # does NOT decide whether we read the repository. Those were conflated
    # once, and the result was that a fork he genuinely worked on -- work
    # living on an unmerged branch, or under a lab's account -- yielded
    # nothing at all: no draft, no material, an empty question. The product
    # decision is explicit that the property kept is provenance, not
    # verification ("did this come from him or from us"), and that the only
    # thing this platform refuses to ship is a sentence with no author. An
    # unproven repository still gets read and still gets drafted; the draft
    # simply reaches him as his claim to make rather than ours to assert.
    #
    # Two conditions must BOTH hold before a language becomes an
    # auto-confirmed skill fact:
    #   1. his commits appear in the repository at all, and
    #   2. for a fork, his side is ahead of upstream -- otherwise a one-line
    #      README fix on a large project donates its whole language profile.
    proven = authorship(snapshot, owner_login=owner_login) is Authorship.OWNED
    facts = (
        write_skill_facts(student=student, snapshot=snapshot)
        if proven and (not snapshot.is_fork or (snapshot.ahead_by or 0) > 0)
        else ()
    )
    evidence = _repo_evidence(ref, snapshot, token=token, transport=transport)
    if facts and evidence.libraries:
        # Same gate as the languages above: only a repository his commits
        # appear in proposes skills in his name. Unconfirmed either way.
        facts += write_library_skill_facts(
            student=student, snapshot=snapshot, libraries=evidence.libraries
        )
    proposal = (
        propose_description(
            _parser(client),
            student_id=str(student.id),
            project_name=ref.name,
            evidence=evidence.text,
        )
        if evidence.text
        else None
    )
    if facts and proposal is not None and proposal.techniques:
        # The model's reading of the project's own prose, under the same gate
        # as the languages and libraries above and unconfirmed like the
        # libraries: a technique is a claim until he makes it his.
        facts += write_technique_skill_facts(
            student=student, snapshot=snapshot, techniques=proposal.techniques
        )
    # first_commit/last_commit come from the newest _COMMITS_PER_PAGE commits
    # of the whole repository, not necessarily the student's own (see
    # facts.write_project_fact's docstring, which is honest about this).
    # When the fetch was capped, that range may also be truncated -- older
    # history the sample never reached -- so drop it rather than show a
    # wrong or misattributed span. When it is shown, word it as the
    # repository's own span, not something "we found" about him.
    span = (
        f" (the repository's commits span {snapshot.first_commit:%b %Y} to "
        f"{snapshot.last_commit:%b %Y})"
        if snapshot.first_commit
        and snapshot.last_commit
        and not snapshot.commit_sample_capped
        else ""
    )
    # A draft he edits beats a blank box, and the mechanical facts make the
    # question specific. He is still the author of whatever he accepts -- which
    # is why an unproven repository can be drafted from safely: the prompt
    # forbids the model from characterising his role or naming who else worked
    # on it, so the draft describes the code and leaves authorship to him.
    if proven:
        opening = f"We found {snapshot.commit_count} commits in {ref.name}{span}."
    elif snapshot.is_fork:
        parent = snapshot.parent or "another repository"
        opening = (
            f"{ref.owner}/{ref.name} is a fork of {parent} with no commits from "
            "you on the default branch, so we cannot record it as your work on "
            "the repository's evidence alone."
        )
    else:
        opening = (
            f"We see no commits from you in {ref.owner}/{ref.name}, so we cannot "
            "record it as your work on the repository's evidence alone."
        )

    if proposal is not None and proven:
        ask = "Does this description look right, or would you correct it?"
    elif proposal is not None:
        ask = (
            "Here is what the code itself does — what was your role in it, and "
            "would you correct this description?"
        )
    elif proven:
        ask = "What were you building, and what came out of it?"
    else:
        ask = "What was your role?"

    return IntakeResult(
        outcome=Outcome.NEEDS_INPUT,
        facts=facts,
        proposal=proposal,
        question=f"{opening} {ask}",
    )


@dataclass(frozen=True)
class _Evidence:
    text: str
    #: (name, number of parsed files importing it), most-imported first. A
    #: manifest-declared name that no parsed file imports carries 0 -- declared
    #: is evidence enough to propose it, just weaker than declared and used.
    libraries: tuple[tuple[str, int], ...]


def _repo_evidence(
    ref: RepoRef,
    snapshot: RepoSnapshot,
    *,
    token: str | None,
    transport: Transport | None,
) -> _Evidence:
    """Text for the model, assembled in the spec's signal-ladder order.

    The rungs, and why they are ranked this way, are in signals.py. The order
    here matters because the result is truncated at _MAX_EVIDENCE_CHARS: what
    is appended first survives. Docstrings and definitions lead, README
    trails, and requirements.txt is never read at all -- the repository this
    was validated against has one that is a pip freeze of the author's
    operating system.
    """
    chunks = [f"Repository: {ref.owner}/{ref.name}"]
    if snapshot.description:
        chunks.append(f"Description: {snapshot.description}")

    paths = snapshot.tree_paths or snapshot.file_names
    # The repository's own module names, so an absolute `import copasi_parser`
    # is not reported as a technology alongside numpy.
    local = local_module_names(paths)
    parsed = []
    for path in interesting_paths(paths, limit=_MAX_PARSED_FILES):
        text = fetch_file(ref, path, token=token, transport=transport)
        if text:
            parsed.append(file_signals(path, text, local=local))

    # Rungs 1, 2 and 5: prose the author wrote, next to what it describes.
    for signal in parsed:
        body = []
        if signal.module_doc:
            body.append(signal.module_doc)
        for name, doc in signal.definitions[:_MAX_DEFINITIONS_PER_FILE]:
            body.append(f"{name}: {doc}" if doc else name)
        for cell in signal.markdown[:_MAX_MARKDOWN_CELLS]:
            body.append(cell)
        if body:
            chunks.append(f"--- {signal.path} ---\n" + "\n".join(body))

    # Rung 3: what the code actually imports, and how often. The count is the
    # ranking evidence -- without it the cut downstream is alphabetical, which
    # keeps `ase` and drops `torch`.
    counts = Counter(name for signal in parsed for name in signal.imports)

    # Rung 3b: what the project declares it asks for. Fetched by name because
    # interesting_paths selects source and prose, not manifests. Python is
    # absent from MANIFEST_FILES on purpose: its manifest can be a pip freeze.
    for name in MANIFEST_FILES:
        if name not in snapshot.file_names:
            continue
        for declared in manifest_libraries(
            name, fetch_file(ref, name, token=token, transport=transport)
        ):
            counts.setdefault(declared, 0)

    libraries = tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    if libraries:
        chunks.append("Imported libraries: " + ", ".join(name for name, _ in libraries))

    # Rung 4.
    directories = directory_names(paths, limit=_MAX_DIRECTORIES)
    if directories:
        chunks.append("Directories: " + ", ".join(directories))

    # Rung 6.
    if snapshot.commit_messages:
        chunks.append("Commit subjects: " + "; ".join(snapshot.commit_messages))

    # Rung 7, last of the prose rungs: present but not first, because a README
    # is absent or useless exactly when it is most needed.
    for name in SIGNAL_FILES:
        if name in snapshot.file_names and not any(s.path == name for s in parsed):
            text = fetch_file(ref, name, token=token, transport=transport)
            if text:
                chunks.append(f"--- {name} ---\n{text}")

    return _Evidence(
        text="\n\n".join(chunks)[:_MAX_EVIDENCE_CHARS],
        libraries=libraries,
    )


def _document(
    student: Membership,
    document: DocumentVersion,
    client: object | None,
    store: ReadableObjectStore | None = None,
) -> IntakeResult:
    """An uploaded thesis or project report.

    Almost nothing here is mechanical -- that the file exists, and who uploaded
    it. Everything about its content is read by a model, so the outcome is
    always NEEDS_INPUT and nothing is written until he accepts a description.
    """
    text = extract_text(open_document(document, store=store), limit=_MAX_DOCUMENT_CHARS)
    if not text.strip():
        return IntakeResult(
            outcome=Outcome.FAILED,
            reason="no text layer in the document; OCR is out of scope",
        )
    proposal = propose_description(
        _parser(client),
        student_id=str(student.id),
        # DocumentVersion carries no human-readable field (no filename, no
        # title -- object_key is a quarantine path keyed on the row's own
        # UUID; see apps/concierge/documents.py::register), so this is
        # always the generic-phrase fallback, never a bare UUID landing in
        # the prompt as "DATA -- document text for 3f2a...".
        project_name="the uploaded document",
        evidence=text,
        source_kind="document text",
    )
    return IntakeResult(
        outcome=Outcome.NEEDS_INPUT,
        proposal=proposal,
        question=(
            "Does this description of your document look right, or would you "
            "correct it?"
            if proposal is not None
            else "What was this project about, and what came out of it?"
        ),
        # A ceiling has to exist -- this is the cost limiter on the call above
        # -- but a description drawn from part of a document must not be
        # offered as if it were drawn from all of it. The student is about to
        # accept or correct these words; what the model did not read changes
        # how they should read them.
        reason=(
            f"the document is longer than {_MAX_DOCUMENT_CHARS:,} characters; "
            "this description covers its opening only"
            if len(text) == _MAX_DOCUMENT_CHARS
            else None
        ),
    )


def _parser(client: object | None) -> ResponsesAPI:
    if client is not None:
        return cast(ResponsesAPI, getattr(client, "responses", client))
    return cast(ResponsesAPI, OpenAI().responses)


def ingest_evidence(
    *,
    student: Membership,
    raw_source: str = "",
    owner_login: str,
    document: DocumentVersion | None = None,
    token: str | None = None,
    transport: Transport | None = None,
    client: object | None = None,
    store: ReadableObjectStore | None = None,
) -> IntakeResult:
    """Ingest one artefact the student has named.

    The token, if given, is used inside this call and never returned, stored or
    logged. Intake is one-shot: facts persist, access does not, which is why no
    secret store is needed here (see CLAUDE.md on credentials never living in
    the database).

    owner_login must come from a verified GitHub account link on the
    student's own profile -- never a free-text form field, and never
    ref.owner parsed from the pasted repository URL. repo.py's authorship()
    reduces entirely to `contributors.get(owner_login, 0) > 0`; an
    owner_login the caller did not verify turns that gate off. Concretely:
    `ingest_evidence(student=..., raw_source="https://github.com/torvalds/linux",
    owner_login="torvalds")` returns OWNED and writes C, Assembly and Shell
    as auto-confirmed skill facts for a student who has never touched that
    repository. The interaction surface (the view that will collect this
    value) does not exist yet, which is exactly why the constraint has to
    live here rather than in a form validator.
    """
    if rate_limited(
        "evidence_intake",
        student.id,
        limit=_INTAKE_RATE_LIMIT,
        window_seconds=_INTAKE_RATE_WINDOW_SECONDS,
    ):
        raise EvidenceRateLimited("evidence intake rate limit exceeded")
    # A document is identified by the row, not by a pasted string, so it never
    # goes through parse_source. open_document refuses anything GuardDuty has
    # not marked AVAILABLE, and that ordering must stay first.
    if document is not None:
        return _document(student, document, client, store)
    try:
        ref = parse_source(raw_source)
    except UnsupportedSource as error:
        return IntakeResult(outcome=Outcome.FAILED, reason=str(error))
    if isinstance(ref, DoiRef):
        return _publication(student, ref, transport)
    return _repository(
        student,
        ref,
        owner_login=owner_login,
        token=token,
        transport=transport,
        client=client,
    )
