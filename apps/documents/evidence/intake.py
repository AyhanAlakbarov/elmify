"""The DOI path, and the text a reading is made from (CV evidence spec §7.2, §8, §13).

ingest_evidence reads one DOI into a confirmed publication fact -- the only
caller of the DOI path, kept for `manage.py ingest_evidence --source`.
Repositories and theses are no longer ingested one at a time: refresh.py finds
them and reads them with the helpers below.

THREE OUTCOMES. NEEDS_INPUT is not a soft failure: the fetch worked and the
record needs the student (which author is he; is this preprint published).

This module writes nothing itself (tests/documents/evidence/test_invariants.py);
it imports models for annotations only.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from apps.concierge.documents import ReadableObjectStore, open_document
from apps.concierge.models import DocumentVersion
from apps.ratelimit import rate_limited
from apps.tenancy.models import Membership

from ..ingestion import extract_link_urls, extract_text
from ..models import VerifiedFact
from .facts import UnusablePublication, write_publication_fact
from .github import GitHub
from .publication import PublicationNotFound, fetch_publication
from .repo import RepoSnapshot, fetch_files
from .signals import (
    AGENT_NOTES,
    MANIFEST_FILES,
    PROSE_SUFFIXES,
    directory_names,
    file_signals,
    interesting_paths,
    local_module_names,
    manifest_libraries,
    strip_markup,
)
from .sources import DoiRef, RepoRef, UnsupportedSource, parse_source
from .transport import Transport

#: A model reading a repository does not need the whole repository.
MAX_EVIDENCE_CHARS = 24_000
#: A thesis runs to 150,000-300,000 characters; this reads a whole master's thesis
#: and is still the cost ceiling on a per-student paid call.
MAX_DOCUMENT_CHARS = 200_000
MAX_README_CHARS = 6_000
MAX_AGENT_NOTES_CHARS = 3_000
#: One notebook's converted text, cut after parsing -- never the JSON.
MAX_NOTEBOOK_CHARS = 8_000
#: Each parsed file is one alias in the RepoFiles query: the cost dial of the selection.
_MAX_PARSED_FILES = 12
_MAX_DEFINITIONS_PER_FILE = 20
_MAX_MARKDOWN_CELLS = 12
_MAX_DIRECTORIES = 40
#: Model reads per student per hour (spec §12.1). Shared by this DOI path and
#: refresh.py's model reads -- one bucket, "evidence_intake".
INTAKE_RATE_LIMIT = 20
INTAKE_RATE_WINDOW_SECONDS = 3600
#: Shorter logins are common words and name nobody.
_MIN_SCRUBBED_LOGIN = 3


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


def ingest_evidence(
    *, student: Membership, raw_source: str, transport: Transport | None = None
) -> IntakeResult:
    """Ingest one DOI the student named. Rate-limited per student."""
    if rate_limited(
        "evidence_intake",
        student.id,
        limit=INTAKE_RATE_LIMIT,
        window_seconds=INTAKE_RATE_WINDOW_SECONDS,
    ):
        raise EvidenceRateLimited("evidence intake rate limit exceeded")
    try:
        ref = parse_source(raw_source)
    except UnsupportedSource as error:
        return IntakeResult(outcome=Outcome.FAILED, reason=str(error))
    if not isinstance(ref, DoiRef):
        return IntakeResult(
            outcome=Outcome.FAILED,
            reason=(
                "repositories are read by refresh_evidence, from the student's "
                "GitHub username; --source takes a DOI"
            ),
        )
    return _publication(student, ref, transport)


@dataclass(frozen=True)
class Evidence:
    text: str
    #: (name, number of parsed files importing it), most-imported first; a
    #: manifest-declared name no parsed file imports carries 0.
    libraries: tuple[tuple[str, int], ...]
    #: Characters after the description: what refresh.EVIDENCE_FLOOR measures.
    body_chars: int


def _scrub(text: str, login: str) -> str:
    """The student's login never reaches a prompt (spec §7.2 item 1, Review Focus 2)."""
    if len(login) < _MIN_SCRUBBED_LOGIN:
        return text
    return re.sub(
        rf"(?<![A-Za-z0-9-]){re.escape(login)}(?![A-Za-z0-9-])",
        "the author",
        text,
        flags=re.IGNORECASE,
    )


def repo_evidence(snapshot: RepoSnapshot, *, github: GitHub, login: str) -> Evidence:
    """Text for the model in the spec §7.2 order; what is appended first survives the cut.

    Every file it needs comes in ONE RepoFiles query (spec §7.1): the selection,
    the manifests and the agent notes at the root. The root READMEs came with the
    snapshot. RepoNotAccessible propagates when that query fails.
    """
    paths = snapshot.tree_paths or snapshot.file_names
    local = local_module_names(paths)
    selected = interesting_paths(paths, limit=_MAX_PARSED_FILES, sizes=snapshot.sizes)
    named = [name for name in (*MANIFEST_FILES, *AGENT_NOTES) if name in snapshot.file_names]
    texts = {
        **fetch_files(
            snapshot.ref,
            [path for path in (*selected, *named) if path not in snapshot.readmes],
            github=github,
            sizes=snapshot.sizes,
        ),
        **snapshot.readmes,
    }
    parsed = [
        file_signals(path, texts[path], local=local) for path in selected if texts.get(path)
    ]
    notebooks = [s for s in parsed if s.path.endswith(".ipynb")]
    prose = [s for s in parsed if s.path.endswith(PROSE_SUFFIXES)]
    code = [s for s in parsed if s not in notebooks and s not in prose]

    body: list[str] = []
    for signal in code:  # 2: code signals
        lines = [signal.module_doc] if signal.module_doc else []
        lines += [
            f"{name}: {doc}" if doc else name
            for name, doc in signal.definitions[:_MAX_DEFINITIONS_PER_FILE]
        ]
        if lines:
            body.append(f"--- {signal.path} ---\n" + "\n".join(lines))
    for signal in notebooks:  # 3: notebooks, shortened after parsing
        lines = [*signal.markdown[:_MAX_MARKDOWN_CELLS], *signal.outputs]
        if lines:
            body.append(f"--- {signal.path} ---\n" + "\n".join(lines)[:MAX_NOTEBOOK_CHARS])

    counts = Counter(name for signal in parsed for name in signal.imports)  # 4: libraries
    for name in MANIFEST_FILES:
        for declared in manifest_libraries(name, texts.get(name, "")):
            counts.setdefault(declared, 0)
    libraries = tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    if libraries:
        body.append("Imported libraries: " + ", ".join(name for name, _ in libraries))

    directories = directory_names(paths, limit=_MAX_DIRECTORIES)  # 5
    if directories:
        body.append("Directories: " + ", ".join(directories))

    if snapshot.commit_messages:  # 6
        body.append(
            "Commit messages, newest first:\n"
            + "\n".join(f"- {message}" for message in snapshot.commit_messages)
        )

    readmes = [(s.path, s.markdown[0]) for s in prose if s.markdown]  # 7
    for name, text in snapshot.readmes.items():
        if all(path != name for path, _ in readmes):
            readmes.append((name, text))
    for path, text in readmes:
        if cleaned := strip_markup(text)[:MAX_README_CHARS]:
            body.append(f"--- {path} ---\n{cleaned}")

    for name in AGENT_NOTES:  # 8
        if text := texts.get(name, ""):
            body.append(f"--- {name} ---\n{text[:MAX_AGENT_NOTES_CHARS]}")

    head = _scrub(f"Description: {snapshot.description}", login) if snapshot.description else ""
    rest = _scrub("\n\n".join(body), login)
    text = "\n\n".join(part for part in (head, rest) if part)[:MAX_EVIDENCE_CHARS]
    return Evidence(text=text, libraries=libraries, body_chars=len(rest))


def document_text(
    document: DocumentVersion, *, store: ReadableObjectStore | None = None
) -> str:
    """An uploaded thesis or report's text, to MAX_DOCUMENT_CHARS.

    open_document refuses anything GuardDuty and the upload check did not pass
    (DocumentUnavailable); that ordering stays first. UnsupportedUpload for a
    file pypdf cannot read; "" for one with no text layer (OCR is out of scope).
    """
    return extract_text(open_document(document, store=store), limit=MAX_DOCUMENT_CHARS)


def cv_links(
    document: DocumentVersion, *, store: ReadableObjectStore | None = None
) -> tuple[RepoRef, ...]:
    """The GitHub repositories a CV links, re-extracted now (links are stored nowhere).

    UnsupportedUpload when the CV does not parse: extract_link_urls answers () for
    that, and refresh.py must not read "unreadable" as "links nothing" -- the repos
    only the CV links would lose their readings (spec §6).
    """
    content = open_document(document, store=store)
    extract_text(content)
    refs: list[RepoRef] = []
    for url in extract_link_urls(content):
        try:
            ref = parse_source(url)
        except UnsupportedSource:
            continue
        if isinstance(ref, RepoRef) and ref.host == "github":
            refs.append(ref)
    return tuple(dict.fromkeys(refs))
