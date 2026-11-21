"""Data models and question specifications for the fact ledger gap review."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from apps.documents.models import VerifiedFact
from apps.documents.verification import unsuperseded_facts
from apps.tenancy.models import Membership


class Kind(StrEnum):
    MISSING_CONTACT = "MISSING_CONTACT"
    #: The student's surname / given name as in the passport, asked only when an
    #: open application's file-name rule uses {surname} or {given_name}. The
    #: answer is the student's own and is stored confirmed (see answer_questions).
    NAME_PARTS = "NAME_PARTS"
    MISSING_GRADE = "MISSING_GRADE"
    INCOMPLETE_ENTRY = "INCOMPLETE_ENTRY"
    #: A programme's page asked for a field (derive.Directive `include`) that
    #: the ledger has no value for. The student supplies their own fact; the
    #: page's sentence is the evidence, shown as the programme's words.
    #: Surfaced either from an explicit `programme` argument or from active CV
    #: `DocumentDraft.requirements` (`RequirementList`).
    PROGRAMME_REQUIRED = "PROGRAMME_REQUIRED"
    #: The one question here that does not correct an existing fact: money the
    #: student never thought to list. Answering it CREATES an award rather than
    #: superseding one, which is why GapQuestion.fact_id is optional.
    MISSING_AWARD = "MISSING_AWARD"
    #: A language entry with no certificate, no CEFR level, or both.
    MISSING_LANGUAGE = "MISSING_LANGUAGE"
    #: The degree's own thesis, its supervisor, or the student's class rank.
    MISSING_DEGREE_DETAIL = "MISSING_DEGREE_DETAIL"
    #: A degree title or institution written short ("B.Sc. of Chem. Eng.",
    #: "UFAZ"), asked for as the diploma prints it. The engine never expands a
    #: short form itself (R-034, R-061, S-029; CV design 2026-10-12 §5.3).
    ABBREVIATED_NAME = "ABBREVIATED_NAME"
    #: What language the student's highest completed degree was taught in.
    MEDIUM_OF_INSTRUCTION = "MEDIUM_OF_INSTRUCTION"
    #: A citation with no resolvable identifier, no author position, or no year.
    MISSING_PUBLICATION_DETAIL = "MISSING_PUBLICATION_DETAIL"
    #: A whole category the ledger holds no facts of at all -- voluntary work,
    #: a referee.
    ABSENT_SECTION = "ABSENT_SECTION"
    #: A degree ETH's own instructions say must be listed and nobody
    #: volunteers -- an exchange semester, an unfinished programme -- plus the
    #: student-society role Toronto, Cambridge and HKS all ask for.
    EDUCATION_COMPLETENESS = "EDUCATION_COMPLETENESS"
    #: A span longer than three months that no education, experience or
    #: timeline entry covers -- including the span from the last entry to
    #: today. A question since the TIMELINE category exists to hold the
    #: answer; it was a note for as long as it did not.
    TIMELINE_GAP = "TIMELINE_GAP"


#: include-target section -> the fact category that carries the field.
_TARGET_CATEGORY = {
    "education": VerifiedFact.Category.EDUCATION,
    "experience": VerifiedFact.Category.EXPERIENCE,
    "research": VerifiedFact.Category.RESEARCH,
    "personal": VerifiedFact.Category.IDENTITY,
}


@dataclass(frozen=True)
class GapQuestion:
    kind: Kind
    #: The fact this question is about. An answer supersedes it (see
    #: answer_question) rather than writing a second row for the same thing.
    #: None for a question about something the ledger does not hold at all --
    #: then `category` says what an answer creates.
    fact_id: UUID | None
    #: The payload key the answer lands in. Must be a key the fact's category
    #: already carries -- answer_question refuses anything else.
    payload_key: str
    #: What the student is asked. One line or one number to answer.
    prompt: str
    #: What in the student's own material triggered this. A question they
    #: cannot trace reads as a machine guessing, and they stop answering.
    evidence: str
    #: The category an answer CREATES, for a question with no fact_id. Set by
    #: the detector, never by the form: it decides which table the student's
    #: sentence lands in, so a posted one would be a category-confusion bug
    #: wearing a trust boundary.
    category: str | None = None
    #: Names what a create-path question BUILDS, so several questions can fill
    #: one new fact and two questions writing the same key stay distinct. It is
    #: also half the form field name (gap_intake.field_name), so it must be
    #: stable between a render and the submit that follows it -- the detector's
    #: own name for the question, never anything derived from a row's position.
    #:
    #: Required whenever fact_id is None: without it every create-path question
    #: posts under "None:<key>", and two of them share one input.
    slug: str | None = None
    #: Every payload key this question's GROUP needs answered before
    #: answer_questions writes the fact -- not just this question's own key.
    #: Server-built and identical on every question of a group, like `category`
    #: and for the same reason: it decides whether a half-answered group is
    #: written, which is a trust decision the form must not reach.
    #:
    #: It travels on the question rather than in a table keyed by slug because
    #: a timeline gap's slug names the span it is about
    #: ("timeline-gap:2023-06-30:2023-11-01") and cannot be a module constant.
    #:
    #: Required whenever fact_id is None. Without it every create-path group
    #: would be written from whatever subset the student happened to answer.
    group_keys: tuple[str, ...] = ()
    #: Payload values the DETECTOR supplies, which nobody is asked for: a
    #: voluntary role is unpaid by construction, and a timeline entry's dates
    #: are the gap the detector found. Merged after the completeness check, so
    #: a default never counts as an answer.
    defaults: tuple[tuple[str, str | bool], ...] = ()

    def __post_init__(self) -> None:
        if self.fact_id is None and self.slug is None:
            raise ValueError("a question with no fact must carry a slug")
        if self.fact_id is None and not self.group_keys:
            raise ValueError("a question with no fact must declare its group keys")


@dataclass(frozen=True)
class GapNote:
    """Something worth reading that nobody is asked to answer.

    Its own type, not a GapQuestion with a null payload_key: a note has no
    fact to supersede, no key to land in and no answer, so putting it in the
    question tuple would push a nullable key through answer_questions,
    submit_answers and field_name -- the entire write path, which is the only
    part of this module with a trust boundary in it -- for a thing that never
    writes.

    Notes are the preferred output wherever the student cannot act: one costs
    a second to read and skip, a question costs a decision, and a long form
    is where a student abandons.
    """

    #: What the counsellor and student read. A statement, not a request.
    text: str
    #: What in the student's own material produced it, same contract as
    #: GapQuestion.evidence.
    evidence: str


class UnanswerableQuestion(ValueError):
    """An answer cannot be written: wrong student, wrong key, or a fact whose
    tier a typed sentence may not overwrite.

    Not raised for a blank answer -- every question is skippable, and a skip is
    an ordinary outcome rather than an error.
    """


#: slug -> (fact category, ((payload key, prompt), ...)) for every question
#: group that BUILDS a new fact rather than correcting one.
#:
#: One table, because a group used to be described in three places -- its key
#: list here, its prompts in the detector, its category in both -- and a
#: detector whose keys drifted from the declared list could never be written
#: at all: answer_questions writes a created fact only when every declared key
#: was answered, so a mismatch fails silently and forever.
#:
#: Evidence is NOT here. It is the detector's, because one group's evidence
#: counts the student's own rows ("Your CV lists 2 award(s), none with an
#: amount or terms") and cannot be a constant.
_GROUPS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "merit-award": (
        VerifiedFact.Category.AWARD,
        (
            (
                "title",
                "Have you ever been awarded a scholarship, stipend, fee waiver or "
                "tuition reduction on academic merit -- including a partial one, such "
                "as a 10% fee reduction? Name it and who awarded it. If one is already "
                "on your CV, give its amount or terms instead.",
            ),
        ),
    ),
    "voluntary-role": (
        VerifiedFact.Category.EXPERIENCE,
        (
            (
                "employer",
                "Have you done any voluntary, community or society work? Which "
                "organisation was it with?",
            ),
            ("title", "What was your role there?"),
            (
                "bullets",
                "What did you do in that role? One or two lines, starting with what "
                "you did rather than what you were responsible for.",
            ),
        ),
    ),
    "referee": (
        VerifiedFact.Category.REFERENCE,
        (
            (
                "name",
                "Who would write you a reference -- a supervisor or a lecturer who "
                "knows your work? Give one name; we will ask for their details "
                "when a destination needs them.",
            ),
        ),
    ),
    "exchange-programme": (
        VerifiedFact.Category.EDUCATION,
        (
            (
                "institution_original",
                "Did you spend a semester or a year at another university -- an "
                "Erasmus or exchange programme, or part of a double degree? Which "
                "university was it?",
            ),
            (
                "degree_as_awarded",
                "What was that exchange or double-degree programme called?",
            ),
        ),
    ),
    "unfinished-programme": (
        VerifiedFact.Category.EDUCATION,
        (
            (
                "institution_original",
                "Did you start any degree or programme you did not finish? Which "
                "university was it at?",
            ),
            ("degree_as_awarded", "What was that programme called?"),
        ),
    ),
    "society-role": (
        VerifiedFact.Category.EXPERIENCE,
        (
            (
                "employer",
                "Have you held a position in a student society, committee or "
                "association? Which one?",
            ),
            ("title", "What was your position there?"),
            (
                "bullets",
                "What did the position involve? One or two lines, starting with "
                "what you did.",
            ),
        ),
    ),
    "upper-secondary": (
        VerifiedFact.Category.EDUCATION,
        (
            (
                "institution_original",
                "Which secondary school did you finish? Give its name as it appears on "
                "your school-leaving certificate.",
            ),
            (
                "degree_as_awarded",
                "What is your school-leaving certificate called -- for example "
                "Attestat or Abitur?",
            ),
        ),
    ),
}

#: Values a create group's fact carries that nobody is asked for. A voluntary
#: role IS unpaid -- the student said so by answering the question -- so asking
#: would be asking twice, and leaving it unset would file voluntary work as
#: paid employment in the one place that splits on it (funder_templates/
#: rhodes.py, R-080). Sparse on purpose: only a group whose answer settles a
#: field by construction belongs here. A society role does not -- a paid
#: student-union officer exists.
_GROUP_DEFAULTS: dict[str, dict[str, str | bool]] = {"voluntary-role": {"unpaid": True}}


def _group_questions(slug: str, kind: Kind, evidence: str) -> tuple[GapQuestion, ...]:
    """Every question in a create-path group, sharing one evidence string.

    `_GROUPS` supplies the category, keys and prompts and `_GROUP_DEFAULTS` the
    values nobody is asked for; both are stamped onto every question of the
    group, because answer_questions reads them off the question rather than
    looking them up by slug -- see GapQuestion.group_keys for why.

    Evidence stays a parameter because a group's evidence counts the student's
    own rows (see missing_award) and cannot be a constant.
    """
    category, asks = _GROUPS[slug]
    keys = tuple(key for key, _ in asks)
    defaults = tuple(sorted(_GROUP_DEFAULTS.get(slug, {}).items()))
    return tuple(
        GapQuestion(
            kind=kind,
            fact_id=None,
            category=category,
            slug=slug,
            group_keys=keys,
            defaults=defaults,
            payload_key=key,
            prompt=prompt,
            evidence=evidence,
        )
        for key, prompt in asks
    )


def _cv_on_file(student: Membership) -> bool:
    """Whether there is a CV to ask about. A passport read writes facts too
    (source_ref "document:..."), and a student who uploaded only a passport has
    no CV whose gaps we could name."""
    return unsuperseded_facts(student).exclude(source_ref__startswith="document:").exists()


def _current(student: Membership, category: str) -> list[VerifiedFact]:
    return list(unsuperseded_facts(student).filter(category=category))


def _already_created(student: Membership, slug: str) -> bool:
    """Whether a create-path group has already been answered.

    A created fact is indistinguishable from any other once it is in the
    ledger -- a voluntary role is an EXPERIENCE row with an employer, a title
    and a bullet, exactly like a job -- so the only thing that can say "we
    already asked this and they answered" is the stamp answer_questions puts
    on its own writes. Same mechanism as profile_bridge.py, which finds its
    own rows by source_ref prefix for the same reason.

    Without it a create-path question re-fires on every page load forever,
    which is nagging, and nagging is how a form gets abandoned.
    """
    return unsuperseded_facts(student).filter(source_ref=f"gap-interview:{slug}").exists()
