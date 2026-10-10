"""Deterministic, LLM-free classifier that checks CV claims against the
VerifiedFact ledger.

``SUPPORTED`` means: an entry with this identity exists in the ledger, is
confirmed, and every *detail this module compares* agrees with it. It does
NOT mean every field on the claim has been verified -- some ``CVContent``
fields (``ExperienceEntry.bullets``, ``ResearchEntry.methods`` /
``outcomes``, ``EducationEntry.degree_english`` / ``institution_english`` /
``grade_native`` / ``grade_scale`` / ``grade_conversion`` / ``ects_credits``,
``LanguageEntry.listening`` / ``reading`` / ``spoken_interaction`` /
``spoken_production`` / ``writing``) are captured in the fact payload for
provenance but are never compared, so a confirmed fact can neither confirm nor
contradict them. They are carried because generation reads the payload: a key
absent here never reaches the model, which would leave it to invent the value
or drop the field.

The language sub-skills are never compared for a second reason on top of that:
no document states a self-assessed level, and comparing them would turn a
student's own correction of one column into a CONFLICTING verdict that blocks
their own draft. ``mother_tongue`` is never compared for the same reason: no
document contradicts it, and comparing it would block a student's own
correction.

``PersonalInformation.email`` is not compared either, and for a different
reason: it has no spec at all. The platform issues that address and stamps it
onto generated content, so there is nothing to agree or disagree with.

Tasks 5 and 6: treat ``SUPPORTED`` as "this entry is real and its compared
details agree", not "this entire entry is verified word for word."
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import cast
from uuid import UUID

from django.db.models import QuerySet
from pydantic import BaseModel

from apps.tenancy.models import Membership

from .hygiene import normalize_text
from .models import VerifiedFact
from .schemas import CVContent


class Verdict(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNCERTAIN = "UNCERTAIN"
    CONFLICTING = "CONFLICTING"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class ClaimVerdict:
    claim_path: str
    claim_text: str
    verdict: Verdict
    fact_id: UUID | None


@dataclass(frozen=True)
class _CategorySpec:
    """How one CVContent field maps onto a fact category.

    ``identity`` decides whether a fact is *about* the same thing as a claim;
    ``detail`` decides whether it agrees. Both are payload keys, so writers and
    this verifier share one vocabulary (see ``fact_payload``).
    """

    field: str
    category: str
    identity: tuple[str, ...]
    detail: tuple[str, ...]
    #: Payload keys, in order, that make the human-readable claim text.
    label: tuple[str, ...]
    #: Payload key a bare string entry (publications/awards/skills) lands in.
    scalar_key: str | None = None


_SPECS: tuple[_CategorySpec, ...] = (
    _CategorySpec(
        field="education",
        category=VerifiedFact.Category.EDUCATION,
        identity=("institution_original", "degree_as_awarded"),
        detail=("city", "country", "start_date", "end_date"),
        label=("degree_as_awarded", "institution_original"),
    ),
    _CategorySpec(
        field="experience",
        category=VerifiedFact.Category.EXPERIENCE,
        identity=("employer", "title"),
        detail=("city", "country", "start_date", "end_date"),
        label=("title", "employer"),
    ),
    _CategorySpec(
        field="research",
        category=VerifiedFact.Category.RESEARCH,
        identity=("thesis_title",),
        detail=("supervisor", "institution", "city", "country", "start_date", "end_date"),
        label=("thesis_title",),
    ),
    _CategorySpec(
        # Identified by title: it is the one part of a citation that is not a
        # formatting choice. Year and DOI are compared because a wrong year
        # inflates a record and a wrong DOI points at someone else's paper.
        field="publications",
        category=VerifiedFact.Category.PUBLICATION,
        identity=("title",),
        detail=("year", "doi"),
        label=("title",),
    ),
    _CategorySpec(
        field="awards",
        category=VerifiedFact.Category.AWARD,
        identity=("title",),
        # An award's date is a claim like any other, so it is compared rather
        # than merely carried. scalar_key is gone with the bare string.
        detail=("date",),
        label=("title",),
    ),
    _CategorySpec(
        # One verdict per skill, as before -- the category is the applicant's
        # own filing choice, carried for provenance but never compared: a
        # student who moves "Python" from Tools to Core competencies has not
        # contradicted anything.
        field="skills",
        category=VerifiedFact.Category.SKILL,
        identity=("name",),
        detail=(),
        label=("name",),
    ),
    _CategorySpec(
        # Identified by name, and the address is compared: a referee's email
        # is how a committee reaches them, so a wrong one is a wrong claim
        # about a third party rather than a formatting difference.
        field="references",
        category=VerifiedFact.Category.REFERENCE,
        identity=("name",),
        detail=("email",),
        label=("name",),
    ),
    _CategorySpec(
        field="languages",
        category=VerifiedFact.Category.LANGUAGE,
        identity=("language",),
        detail=("cefr_level", "test_name", "test_score"),
        label=("language",),
    ),
    _CategorySpec(
        # A summary is the one CVContent field made of assertions rather than
        # records (design doc, "Why summary exists but is off by default"):
        # it must be verified like anything else, against the currently-
        # unused PERSONAL category. None means "no claim" (see
        # verify_against_facts); a populated one with no matching PERSONAL
        # fact is correctly UNSUPPORTED.
        field="summary",
        category=VerifiedFact.Category.PERSONAL,
        identity=("summary",),
        detail=(),
        label=("summary",),
        scalar_key="summary",
    ),
    _CategorySpec(
        # The name is a claim like any other: it is read off a scanned
        # document, so it can be an OCR misread or disagree with a passport,
        # and a human confirms it before it reaches a funder. The contact
        # address is not here -- it is the address the student applies with
        # (see Membership.application_email: the connected mailbox's address,
        # or one the student declared and confirmed) and stamped, never
        # claimed.
        #
        # Appended, not inserted: _SPECS order is verdict order.
        field="personal_information",
        category=VerifiedFact.Category.IDENTITY,
        identity=("full_name",),
        # ORCID is compared: it is a fixed-format identifier, so a difference
        # is a real difference, and a wrong one credits another researcher's
        # record. The three URL fields are carried but never compared -- a
        # trailing slash or a www. is a formatting difference _norm cannot
        # see, and blocking a student's own draft over one would be a false
        # CONFLICTING.
        detail=("orcid",),
        label=("full_name",),
    ),
    _CategorySpec(
        # Identified by its span: two entries cannot describe the same months,
        # and the span is what the gap detector matched on when it asked.
        #
        # The statement IS compared, unlike every other piece of prose in this
        # table. The others (thesis_title, supervisor, funding) are a model's
        # transcription off a document, so comparing them blocks a draft over a
        # transcription difference. This one is the student's own typed
        # sentence, carried in and out unchanged, so a difference is a model
        # having rewritten a person's account of a period of their life --
        # exactly the thing to refuse.
        field="timeline",
        category=VerifiedFact.Category.TIMELINE,
        identity=("start_date", "end_date"),
        detail=("statement",),
        label=("statement",),
    ),
)

_SPEC_BY_CATEGORY = {spec.category: spec for spec in _SPECS}
_PAYLOAD_KEYS = {
    spec.category: spec.identity
    + spec.detail
    # city/country used to be appended here instead of living in spec.detail:
    # carried into the payload, then never compared. A generated CV therefore
    # placed a Strasbourg university in Bosnia and Herzegovina and a Baku one
    # in "AA" while every verdict came back SUPPORTED, because nothing looked.
    # They are detail keys now, so a claim that contradicts the ledger reads
    # CONFLICTING. _details_conflict skips a key either side leaves empty, so
    # an entry whose location the CV never stated still cannot conflict.
    # Captured for provenance, never compared -- see the module docstring on
    # what SUPPORTED does and does not mean. The ledger is append-only, so a
    # fact row written without these keys can't gain them except via a
    # superseding row; that's fine, they're not part of any verdict.
    + (
        (
            "degree_english",
            "institution_english",
            "grade_native",
            "grade_scale",
            "grade_conversion",
            "ects_credits",
            # Carried, never compared, for the same reason as the grade
            # fields: the model splits a degree's thesis title differently
            # run to run, and a rank is transcribed from prose ("3rd of
            # 120", "top 5%").
            "thesis_title",
            "class_rank",
            # supervisor/funding/relevant_coursework join them on the same
            # bargain: a name off a folded line, a funder sentence and a
            # module list are all transcribed prose, so comparing any of them
            # would block a draft over a transcription difference.
            "supervisor",
            "funding",
            "relevant_coursework",
            # medium_of_instruction joins them: it is a sentence transcribed
            # off a certificate ("English", "instruction in English and
            # Azerbaijani"), so comparing it would block a draft over wording.
            "medium_of_instruction",
        )
        if spec.field == "education"
        else ()
    )
    # supervisor joins bullets as carried-but-never-compared. It used to be on
    # the schema and nowhere in the payload: extracted, read by
    # render._section_order, and lost on the way to the ledger, so a CV
    # regenerated from facts demoted a research applicant to the taught order.
    #
    # NOT a spec.detail key, though ResearchEntry compares its own. Extraction
    # is measurably non-deterministic on a name read off a folded line
    # ("EPFL | Prof. Schwaller's group"), and comparing it would turn
    # "Prof. Schwaller" against "Philippe Schwaller" into a CONFLICTING verdict
    # that blocks the applicant's own draft over a formatting difference. The
    # cost is that a genuinely wrong supervisor now reads SUPPORTED; that is
    # the same bargain every other key in this group is on.
    #
    # project rides with them for the same reason: where the model cuts
    # "Research Intern, Project Title: X" between role and project moves run
    # to run, and comparing it would block a draft over the cut.
    # ponytail: identity stays (employer, title), so two same-titled posts at
    # one employer share an identity and the second reads CONFLICTING on its
    # dates; add project to identity once the cut is stable enough to compare.
    #
    # group is the same case as supervisor, read off the same folded line:
    # "EPFL | Prof. Schwaller's group" yields a group on one run and not on
    # the next, and that is not the applicant contradicting anything.
    #
    # unpaid joins them for a different reason: it was extracted by ingestion
    # and then dropped here, so funder_templates/rhodes.py (R-080) and
    # sisgp.py -- both of which section a CV on this flag -- had nothing
    # stored to read and generation re-inferred it from the role's wording on
    # every render. It rides with the carried-not-compared group rather than
    # spec.detail because comparing a bool the model may read differently
    # from a re-ingest ("volunteer tutor" vs "tutor") would turn the
    # applicant's own draft CONFLICTING over a reading difference, not a
    # contradicted fact.
    + (
        ("bullets", "supervisor", "project", "group", "unpaid")
        if spec.field == "experience"
        else ()
    )
    + (("methods", "outcomes", "funding") if spec.field == "research" else ())
    + (
        # An awarding body is read off the line under the award name and a
        # detail line is prose, so both are carried rather than compared --
        # same bargain as the supervisor above. The DATE stays a spec.detail
        # key: a wrong year on an award is a wrong claim, not a formatting
        # difference.
        ("awarding_body", "detail")
        if spec.field == "awards"
        else ()
    )
    + (
        # category/kind/evidence are provenance, never compared: how a skill
        # was derived and what backs it are facts about our reading, not
        # claims the applicant can contradict. A re-ingest that counts
        # differently must not turn his own CV CONFLICTING.
        ("category", "kind", "evidence")
        if spec.field == "skills"
        else ()
    )
    + (
        # volume/issue/pages are carried for the citation but never compared:
        # a registry that omits an issue has a gap in its record, which is not
        # the applicant contradicting anything.
        # is_presentation joins them: it decides which section a citation
        # prints under, so losing it here would silently move a poster into
        # the publication list every time a CV was regenerated from facts.
        (
            "authors",
            "self_author_index",
            "venue",
            "status",
            "volume",
            "issue",
            "pages",
            "is_presentation",
            # The landing page for an item with no DOI. Carried, not compared:
            # unlike a DOI it has no fixed format, so a trailing slash is a
            # difference _norm cannot see.
            "url",
        )
        if spec.field == "publications"
        else ()
    )
    + (
        # phone belongs here for the same reason the URLs do: carried for the
        # contact header, never compared. Its absence was silent data loss --
        # ingestion extracted it into CVContent, this dropped it on the way to
        # the ledger, and generation could then never print a number the
        # applicant had actually given us. cv_base.html renders it when set.
        (
            "phone",
            "linkedin_url",
            "github_url",
            "website_url",
            "github_username",
            "linkedin_handle",
        )
        if spec.field == "personal_information"
        else ()
    )
    #
    # do_not_contact rides with them, and losing it would be worse than losing
    # a phone number: a CV regenerated from the ledger would print a referee
    # the document asked us not to contact with no such note beside them.
    + (
        ("position", "institution", "phone", "do_not_contact")
        if spec.field == "references"
        else ()
    )
    + (
        (
            "listening",
            "reading",
            "spoken_interaction",
            "spoken_production",
            "writing",
            "mother_tongue",
        )
        if spec.field == "languages"
        else ()
    )
    for spec in _SPECS
}


def payload_keys(category: str) -> tuple[str, ...]:
    """The payload keys one category carries.

    Public because a writer outside this module has to reject a key the
    category does not have: a value stored under an unknown key sits where no
    reader looks and no verdict compares it. Returns () for a category with no
    spec rather than raising -- an unknown category is "carries nothing", and
    every caller here treats that as a refusal.
    """
    return _PAYLOAD_KEYS.get(category, ())


def _norm(value: object) -> str:
    """Compare on meaning, not formatting. Empty and missing are the same."""
    if value is None:
        return ""
    return normalize_text(str(value)).casefold()


def fact_payload(entry: object, *, category: str) -> dict[str, object]:
    """Build the canonical fact payload for one CVContent entry.

    Every fact writer in this codebase goes through here (Task 17's profile
    bridge, Task 18's ingestion), so payload keys are defined in exactly one
    place -- the place the verifier reads them from.
    """
    spec = _SPEC_BY_CATEGORY[category]
    if isinstance(entry, str):
        if spec.scalar_key is None:
            raise ValueError(f"{category} facts are not built from a bare string")
        return {spec.scalar_key: entry}
    dumped = cast(BaseModel, entry).model_dump(mode="json")
    return {key: dumped.get(key) for key in _PAYLOAD_KEYS[category]}


def _claim_text(spec: _CategorySpec, payload: dict[str, object]) -> str:
    parts = [str(payload.get(key)) for key in spec.label if payload.get(key)]
    return " at ".join(parts) if len(parts) > 1 else (parts[0] if parts else "")


def fact_label(fact: VerifiedFact) -> str:
    """A ledger row named the way the rest of the codebase names it.

    The same text ``verify_against_facts`` puts in ``ClaimVerdict.claim_text``,
    read off the stored fact rather than off a claim, so both directions share
    one vocabulary. Returns "" for a row whose payload states nothing under its
    category's label keys -- callers treat that as "this row names nothing"
    rather than showing an empty label to a model.
    """
    spec = _SPEC_BY_CATEGORY.get(fact.category)
    return "" if spec is None else _claim_text(spec, _fact_payload(fact))


def _identity(spec: _CategorySpec, payload: dict[str, object]) -> tuple[str, ...]:
    return tuple(_norm(payload.get(key)) for key in spec.identity)


def _fact_payload(fact: VerifiedFact) -> dict[str, object]:
    """A ledger row's ``payload`` is an unconstrained JSONField -- classify a
    malformed one (a list, a bare string, ...) as "states nothing" rather
    than crashing. This function never raises, and that guarantee only holds
    if every read of ``fact.payload`` goes through here."""
    return fact.payload if isinstance(fact.payload, dict) else {}


def _details_conflict(
    spec: _CategorySpec, claim: dict[str, object], fact: dict[str, object]
) -> bool:
    for key in spec.detail:
        stated = _norm(fact.get(key))
        claimed = _norm(claim.get(key))
        if not stated or not claimed:
            # Not stated is not "stated differently" -- on either side: a
            # sparse fact must not conflict with a sparse claim, or vice versa.
            continue
        if stated != claimed:
            return True
    return False


def _classify(
    spec: _CategorySpec, index: int, entry: object, facts: list[VerifiedFact]
) -> ClaimVerdict:
    payload = fact_payload(entry, category=spec.category)
    path = f"{spec.field}[{index}]"
    text = _claim_text(spec, payload)
    identity = _identity(spec, payload)
    if not any(identity):
        # An identity built entirely from missing/empty keys isn't "about"
        # anything -- it must never accidentally match an equally-empty fact
        # and come back a false SUPPORTED.
        return ClaimVerdict(path, text, Verdict.UNSUPPORTED, None)
    matches = [
        fact
        for fact in facts
        if fact.category == spec.category and _identity(spec, _fact_payload(fact)) == identity
    ]
    if not matches:
        return ClaimVerdict(path, text, Verdict.UNSUPPORTED, None)
    for fact in matches:
        if _details_conflict(spec, payload, _fact_payload(fact)):
            return ClaimVerdict(path, text, Verdict.CONFLICTING, fact.id)
    confirmed = next((fact for fact in matches if fact.confirmed_by_id is not None), None)
    if confirmed is not None:
        return ClaimVerdict(path, text, Verdict.SUPPORTED, confirmed.id)
    return ClaimVerdict(path, text, Verdict.UNCERTAIN, matches[0].id)


def spec_entries(content: CVContent, field: str) -> tuple[object, ...]:
    """The claim entries for one spec field.

    Most CVContent fields are tuples. ``summary`` is a ``str`` and
    ``personal_information`` is a ``BaseModel`` -- and a pydantic v2 model is
    iterable, yielding (key, value) pairs, so iterating one directly produces
    a verdict per attribute name instead of one verdict for the entry.
    Anything that is not already a tuple is wrapped. ``None`` means no claim
    was made (summary is the only Optional field among _SPECS), not an empty
    claim, so it yields no entry at all.
    """
    entries = getattr(content, field)
    if entries is None:
        return ()
    return entries if isinstance(entries, tuple) else (entries,)


def verify_against_facts(
    content: CVContent, facts: Iterable[VerifiedFact]
) -> tuple[ClaimVerdict, ...]:
    """Deterministic, LLM-free. Classifies every material claim in ``content``
    against ``facts``; never raises and never mutates ``content`` -- a draft
    carrying UNSUPPORTED claims is still produced so a human has something to
    inspect (spec: 'it classifies; it does not raise')."""
    fact_list = list(facts)
    verdicts: list[ClaimVerdict] = []
    for spec in _SPECS:
        for index, entry in enumerate(spec_entries(content, spec.field)):
            verdicts.append(_classify(spec, index, entry, fact_list))
    return tuple(verdicts)


def unsuperseded_facts(student: Membership) -> QuerySet[VerifiedFact]:
    """Tips of every supersession chain for this student, oldest first.

    Ordered, and that is load-bearing rather than tidiness. Without an ORDER BY
    Postgres returns rows in whatever order it likes; those rows become the
    model's prompt, the model emits CVContent in roughly the order it was given,
    and cv_base.html then groups skills by category. A real CV rendered 22
    skills under 14 headings that way. created_at is the applicant's own order:
    ingest_uploaded_cv writes one row per entry in document order, so oldest
    first restores the order the CV listed things in, and later manual
    additions append. id breaks ties -- a bulk write can share a timestamp, and
    a non-deterministic tiebreak is the same bug again, only rarer.
    """
    return VerifiedFact.objects.filter(
        student=student, superseded_by__isnull=True
    ).order_by("created_at", "id")


def generatable_facts(student: Membership) -> QuerySet[VerifiedFact]:
    """The only facts generation may see: unsuperseded *and* confirmed.

    Spec, 'Machine-generated facts still need a human': a fact whose
    confirmed_by is NULL is a candidate, invisible to generation.
    """
    return unsuperseded_facts(student).filter(confirmed_by__isnull=False)
