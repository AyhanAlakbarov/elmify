"""The counsellor's review: what the ledger is missing, and what it cannot hold.

Fourteen deterministic detectors over the fact ledger, run before generation
rather than after it: twelve unconditional and one programme-gated one in
gap_questions, plus one in gap_notes. Asking after generating burns a
generation, shows a document built on a gap, and then asks; asking first
costs nothing and produces a better first draft.

Two output kinds. A GapQuestion is answerable and writes a fact; a GapNote is
not and writes nothing -- see GapNote on why that is a separate type rather
than a nullable payload_key. Notes are the preferred output wherever the
student cannot act, and one of them exists because the ledger has no shape for
the answer: a certificate (no CERTIFICATE category). A timeline gap was the
other until the TIMELINE category landed, which is the shape of that fix --
the note is the placeholder, and the category is what retires it.

A create-path question group (voluntary work, a referee, an exchange
semester, an unfinished programme, a society role) stops asking once its
group has been answered in full. A created fact is otherwise indistinguishable
from any other fact of its category once it lands -- a voluntary role is an
ordinary EXPERIENCE row -- so the stamp answer_questions writes on its own
creations, ``source_ref=f"gap-interview:{slug}"``, is the only thing that can
tell a created fact from one that arrived some other way. ``_already_created``
reads it back. Same mechanism as ``profile_bridge.py``, which finds its own
rows by a source_ref prefix for the same reason.

A timeline gap is a create group too, and the only one that does not use
``_already_created``: its answer covers the span it was asked about, so the
detector's own arithmetic stops it re-firing. That also makes it the only
question here with no way to be dismissed, which is why the form offers a list
of statements -- answering is the only exit, so there has to be an answer for a
student who will not explain.

No model call anywhere in this module -- these are the checks that need none.
The design's third detector will call one, and the change that wires it up owes
the per-student rate limiter CLAUDE.md requires. Nothing here does, and this
module must not be used as evidence that a limiter exists.

Not here, and not by omission:

- **Country-gated questions** (photo, date of birth, signature, secondary
  school) and the pack-gated ones (German level, ECTS, relevant coursework).
  Both need a pack's countries or disciplines, and funding.RecommendationCandidate
  carries program_name as free text with no country_code and no FK to Program.
  Degradation is the correct behaviour: asking a UK-bound student for a passport
  photo is the mistake, asking nobody is a missed prompt.
- **A thesis grade** (S-027, DE/NL/Nordic). No field holds one -- grade_native
  is the degree's -- and no render decision has been taken about printing it.
- **Talk-vs-poster** ("Was this a talk or a poster?"). No field distinguishes
  the two -- ``PublicationEntry.is_presentation`` is already ``True`` by the
  time this would fire.
- **A certificates section.** No ``VerifiedFact.Category`` holds one, so
  ``gap_notes`` emits a NOTE (``_CERTIFICATES_NOTE``) instead of a question here.
- **Prose rewriting.** A limit, not a backlog item: an accepted rewrite would
  make a model the author of the student's claim on a submitted document.

What the view that first calls this owes, none of which belongs here:

- **Authorisation.** ``answer_questions`` authorises entirely off its
  ``student`` argument -- there is no request to inspect and no role check.
  The view passes the authenticated student's own ``Membership``.
- **Nothing, on the question of a counsellor operating the form.** Decided
  2026-09-11: a counsellor never answers these on a student's behalf. The
  answers become the student's own claims about their own record, and a
  consultant filling them in makes the ledger's provenance a fiction on the
  one surface whose whole purpose is that the student said it. The 403 that
  ``current_membership(request, STUDENT)`` already produces is the intended
  behaviour, not a gap waiting for a counsellor-facing variant, and
  ``tests/documents/test_gap_interview_view.py::test_a_counselor_is_refused``
  is what holds it. A counsellor who spots a wrong answer asks the student to
  correct it.
- **A narrower key allowlist than this module can express.** The guard in
  ``answer_questions`` accepts any key the target's *category* carries, which
  is wider than the set the detectors ask about -- ``payload_keys("SKILL")``
  includes ``category``, ``kind`` and ``evidence``, which are our reading of
  the student's material rather than their claim, and which no question here
  asks for. Contained today (own ledger, ``confirmed_by=None``, so a human
  gates it), but a form that lets the student choose ``payload_key`` freely
  should re-derive the askable ``(fact_id, payload_key)`` pairs from
  ``gap_questions`` instead of trusting the pair it was posted.

Design: docs/superpowers/specs/2026-08-30-cv-gap-interview-design.md
        docs/superpowers/specs/2026-09-16-cv-counsellor-review-design.md
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from django.db import IntegrityError, transaction
from pydantic import ValidationError

from apps.funding.models import Program
from apps.tenancy.models import Membership

from .constraints import directives_from_program
from .dates import parse_cv_date
from .models import VerifiedFact
from .schemas import TIMELINE_STATEMENT_MAX, TimelineEntry, open_span_end
from .verification import payload_keys, unsuperseded_facts


class Kind(StrEnum):
    MISSING_CONTACT = "MISSING_CONTACT"
    MISSING_GRADE = "MISSING_GRADE"
    INCOMPLETE_ENTRY = "INCOMPLETE_ENTRY"
    #: A programme's page asked for a field (derive.Directive `include`) that
    #: the ledger has no value for. The student supplies their own fact; the
    #: page's sentence is the evidence, shown as the programme's words.
    #: No live caller passes a programme yet -- `views.py` and `gap_intake.py`
    #: both call `gap_questions(student)` -- so this kind reaches no screen
    #: today and runs from tests only.
    PROGRAMME_REQUIRED = "PROGRAMME_REQUIRED"
    #: The one question here that does not correct an existing fact: money the
    #: student never thought to list. Answering it CREATES an award rather than
    #: superseding one, which is why GapQuestion.fact_id is optional.
    MISSING_AWARD = "MISSING_AWARD"
    #: A language entry with no certificate, no CEFR level, or both.
    MISSING_LANGUAGE = "MISSING_LANGUAGE"
    #: The degree's own thesis, its supervisor, or the student's class rank.
    MISSING_DEGREE_DETAIL = "MISSING_DEGREE_DETAIL"
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


#: TUM: a CV "must not contain any gaps longer than 3 months". The strictest
#: threshold any source states, so it is the one used: a gap that clears TUM
#: clears ETH, DAAD PRIME (R-011), uni-assist (R-020) and Harvard GSD too.
#: 92 days rather than a month count, because the ledger holds dates.
_MIN_GAP_DAYS = 92


def timeline_gaps(student: Membership) -> tuple[GapQuestion, ...]:
    """Uncovered spans between the education, experience and timeline entries.

    A question since the TIMELINE category exists; it was a NOTE for as long as
    the ledger had nowhere to put the answer. S-045 measured what Cambridge
    actually prints for a gap -- "Full-time carer for family member", "3 months'
    full-time job-hunting" -- and neither has an employer or a bullet, which
    ExperienceEntry requires both of.

    TIMELINE facts are scanned alongside the other two, which is what stops a
    gap being asked twice: an answer covers exactly the span it was asked
    about, so the next run finds the timeline continuous. There is no
    _already_created call here for that reason -- unlike every other create
    group, this detector's own arithmetic tells it the question was answered.

    THE TRAILING SPAN IS A GAP TOO. ETH wants "all details right up to the time
    of application", and the span from the last entry to today is the one most
    likely to exist on a real applicant's CV -- the months between finishing a
    degree and applying. Its answer is stored with NO END DATE, which this
    function already reads as "still running": an end date of today would leave
    the gap reopening a day later and re-firing 93 days after that.

    A between-entries gap's stored span runs from the end of the previous entry
    to the start of the next, so it overlaps each neighbour by a day.
    Deliberate: the alternative is +/- 1 day arithmetic that leaves a one-day
    hole the next run could round back into a gap, and at the month granularity
    the CV prints, the overlap is invisible.

    An entry with no end date is still running, so it covers the timeline up to
    today: end_date=None renders as "present" everywhere else in this codebase
    and means the same thing here. An entry with no start date cannot be placed
    and is skipped rather than guessed at.

    Except an open-ended gap statement, once a later entry has started: it
    stops at that entry's start (schemas.open_span_end), so a post added after
    the trailing gap was answered does not leave the gaps after it unasked.
    """
    current = {
        category: _current(student, category)
        for category in (
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.EXPERIENCE,
            VerifiedFact.Category.RESEARCH,
            VerifiedFact.Category.TIMELINE,
        )
    }
    # Research closes an open gap statement where it is dated, though it
    # covers no span of its own here.
    starts = [
        _read_date(fact.payload.get("start_date") if isinstance(fact.payload, dict) else None)
        for category in (
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.EXPERIENCE,
            VerifiedFact.Category.RESEARCH,
        )
        for fact in current[category]
    ]
    spans: list[tuple[date, date]] = []
    for category in (
        VerifiedFact.Category.EDUCATION,
        VerifiedFact.Category.EXPERIENCE,
        VerifiedFact.Category.TIMELINE,
    ):
        for fact in current[category]:
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            start = _read_date(payload.get("start_date"))
            # An entry that has not started yet -- an accepted place beginning
            # next September -- covers nothing so far. Counted, it would make
            # the months before it a gap ending in the future, and the student
            # would be asked to account for time that has not happened.
            if start is None or start > date.today():
                continue
            end = _read_date(payload.get("end_date"))
            if end is None and category == VerifiedFact.Category.TIMELINE:
                end = open_span_end(start, starts)
            end = end or date.today()
            if end >= start:
                spans.append((start, end))
    # Not `< 2`, as it was while this only looked BETWEEN entries: one entry
    # that ended two years ago is a trailing gap on its own.
    if not spans:
        return ()
    spans.sort()
    questions: list[GapQuestion] = []
    covered_to = spans[0][1]
    for start, end in spans[1:]:
        if (start - covered_to).days > _MIN_GAP_DAYS:
            questions.append(_timeline_question(covered_to, start))
        covered_to = max(covered_to, end)
    if (date.today() - covered_to).days > _MIN_GAP_DAYS:
        questions.append(_timeline_question(covered_to, None))
    return tuple(questions)


def _timeline_question(covered_to: date, start: date | None) -> GapQuestion:
    """One gap, as a question that creates a TIMELINE fact.

    ``start`` is the next entry's start, or None for the span running to today.
    The None case writes no end_date at all -- see timeline_gaps on why.
    """
    until = f"{start:%b %Y}" if start else "now"
    return GapQuestion(
        kind=Kind.TIMELINE_GAP,
        fact_id=None,
        category=VerifiedFact.Category.TIMELINE,
        # The span is in the slug because there can be several gaps on one
        # form and field_name keys on it: two gaps sharing a slug would share
        # one input box. "present" rather than a date for the trailing one,
        # which would otherwise get a new slug -- and a second input -- every
        # day that passes.
        slug=f"timeline-gap:{covered_to:%Y-%m-%d}:{start:%Y-%m-%d}" if start
        else f"timeline-gap:{covered_to:%Y-%m-%d}:present",
        payload_key="statement",
        group_keys=("statement",),
        # The dates are the detector's, not the student's: they are the gap it
        # found, and asking for them would be asking someone to retype what is
        # already on the screen. Sorted by key, matching _group_questions.
        defaults=(
            (("end_date", f"{start:%Y-%m-%d}"), ("start_date", f"{covered_to:%Y-%m-%d}"))
            if start
            else (("start_date", f"{covered_to:%Y-%m-%d}"),)
        ),
        prompt=(
            f"What were you doing between {covered_to:%b %Y} and {until}? One line -- or "
            "pick one of the suggestions. Several destinations require the CV to account "
            "for every month: TUM refuses a gap longer than three months, ETH asks for "
            "periods with no study or work listed explicitly."
        ),
        evidence=(
            f"Nothing on file covers {covered_to:%d %b %Y} to "
            + (f"{start:%d %b %Y}." if start else "today.")
        ),
    )


def _read_date(raw: object) -> date | None:
    """A ledger date as a date, or nothing. Never a guess.

    The ledger stores dates as the CV printed them ("June 2024", "2024-06-30"),
    so parse_cv_date does the reading. Unparseable is None and the entry is
    skipped: a span placed on a misread date invents a gap the student has to
    argue with.
    """
    if not raw:
        return None
    return parse_cv_date(raw)


#: Sections the catalog wants and this ledger cannot hold.
#:
#: Certificates and training (S-036, from Queensland, Toronto, Berkeley and
#: German guidance) is a real gap and an unanswerable question: there is no
#: VerifiedFact category for a certificate, no CVContent entry and no
#: template section. That absence IS S-036's complaint -- the real CV filed a
#: summer school under Awards because there was nowhere else -- and it is why
#: this is a note. A CERTIFICATE category is its own change: a model choice,
#: a _CategorySpec, a schema entry, _PAYLOAD_KEYS, an ingestion sentence, a
#: render section and a Europass mapping.
_CERTIFICATES_NOTE = GapNote(
    text=(
        "Certificates, licences, professional registration and short courses "
        "belong in their own section, and this CV has nowhere to put them yet. "
        "If you hold any, keep the paperwork -- we will ask once there is a "
        "place for it."
    ),
    evidence=(
        "Queensland, Toronto, Berkeley and German guidance all list a "
        "certificates or training section; nothing on file holds one."
    ),
)


def gap_notes(student: Membership) -> tuple[GapNote, ...]:
    """Everything worth showing that nobody is asked to answer.

    One detector left. Timeline gaps were the other, until the TIMELINE
    category gave their answer somewhere to live.
    """
    if unsuperseded_facts(student).exists():
        return (_CERTIFICATES_NOTE,)
    return ()


#: (payload key, alternative key that also counts as present, prompt).
#: The alternative exists because extract_link_urls recovers addresses from a
#: PDF's link annotations while the prompt refuses to build a URL from a bare
#: handle -- so a CV printing "Github: 0rkhann" yields a username and no URL,
#: and is not missing anything a student needs to retype.
_CONTACT_FIELDS: tuple[tuple[str, str | None, str], ...] = (
    ("orcid", None, "What is your ORCID iD?"),
    ("linkedin_url", "linkedin_handle", "What is your LinkedIn profile address?"),
    ("github_url", "github_username", "What is your GitHub profile address?"),
    ("website_url", None, "Do you have a personal or academic website?"),
    ("phone", None, "What phone number should the CV print?"),
)


def _current(student: Membership, category: str) -> list[VerifiedFact]:
    return list(unsuperseded_facts(student).filter(category=category))


def missing_contact(student: Membership) -> tuple[GapQuestion, ...]:
    """Contact details the header has no value for.

    Cheapest to detect and cheapest to answer, so this should never be the
    reason a CV is weak. Asks only for what is genuinely absent.
    """
    fact = unsuperseded_facts(student).filter(category=VerifiedFact.Category.IDENTITY).last()
    if fact is None:
        return ()
    payload = fact.payload if isinstance(fact.payload, dict) else {}
    name = str(payload.get("full_name") or "your CV")
    return tuple(
        GapQuestion(
            kind=Kind.MISSING_CONTACT,
            fact_id=fact.id,
            payload_key=key,
            prompt=prompt,
            evidence=f"The contact header for {name} has no {key.replace('_', ' ')}.",
        )
        for key, alternative, prompt in _CONTACT_FIELDS
        if not payload.get(key) and not (alternative and payload.get(alternative))
    )


def missing_language_detail(student: Membership) -> tuple[GapQuestion, ...]:
    """A language entry with no certificate and no level.

    The test score is the highest-value question in this module. R-041 and
    S-014 both want it, nearly every international programme asks for a
    certificate, and the real CV printed "English -- Advanced (C1)" with
    nothing behind it. Asked first for that reason.

    Never asked of a mother tongue: "no IELTS" is the correct state for one,
    and asking reads as not having read the CV. The LEVEL is still asked, for
    a mother tongue too -- the ledger prints one, and R-041 wants a CEFR value
    in Europe.

    The score and the test name are one question with one input, because a
    score without its test ("7.5") means nothing and two inputs for one fact
    the student reads off one certificate is two decisions for one answer. The
    answer lands in test_score verbatim; test_name stays for a source that
    states them apart.
    """
    scores: list[GapQuestion] = []
    levels: list[GapQuestion] = []
    for fact in _current(student, VerifiedFact.Category.LANGUAGE):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        language = str(payload.get("language") or "this language")
        if not payload.get("test_score") and not payload.get("mother_tongue"):
            scores.append(
                GapQuestion(
                    kind=Kind.MISSING_LANGUAGE,
                    fact_id=fact.id,
                    payload_key="test_score",
                    prompt=(
                        f"Do you have a language certificate for {language} -- an "
                        "IELTS, TOEFL, DELF, TestDaF or Cambridge result? Give the "
                        "test and the score together, for example 'IELTS 7.5'."
                    ),
                    evidence=f"{language} is on file with no test result.",
                )
            )
        if not payload.get("cefr_level"):
            levels.append(
                GapQuestion(
                    kind=Kind.MISSING_LANGUAGE,
                    fact_id=fact.id,
                    payload_key="cefr_level",
                    prompt=(
                        f"What is your level in {language} on the CEFR scale -- "
                        "A1 to C2, or 'native'?"
                    ),
                    evidence=f"{language} is on file with no CEFR level.",
                )
            )
    return tuple(scores) + tuple(levels)


def missing_grade(student: Membership) -> tuple[GapQuestion, ...]:
    """A degree the ledger has no mark for.

    One question per degree, asking for the mark and its scale together --
    S-027 puts the grade on the institution's own scale, mark and denominator
    together (16.45/20.0, 3.82/4.0). Never asks for a conversion: 16.45/20.0
    is the claim, and a 4.0-scale equivalent is a new claim nobody made, with
    tables that differ between the institution, the destination country and
    the credential evaluator.

    Deliberately does not ask how many semesters the grade covers. Searched
    for S-027; no source states it, and the degree's own date range already
    carries the period. Recorded as a negative result so nobody re-derives it.

    Until a transcript is ingested this asks for grades a transcript already
    carries -- the check reads the ledger, so it needs no change when that
    lands, and a missing grade is a real defect on a graduate application in
    the meantime.
    """
    questions: list[GapQuestion] = []
    for fact in _current(student, VerifiedFact.Category.EDUCATION):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        if payload.get("grade_native"):
            continue
        degree = str(payload.get("degree_as_awarded") or "your degree")
        institution = str(payload.get("institution_original") or "")
        # A fourth-year applicant has no final mark, and "what grade did you
        # finish with" is the wrong question for them -- measured on the real
        # CV, whose in-progress MSc was asked exactly that. Cambridge's own
        # worked sample prints the in-progress form: "Second Year, 2.1
        # expected". So the question checks completion first and asks for a
        # grade so far, which is a real fact, rather than a final one, which
        # does not exist yet. Owner correction 2026-09-16.
        if _degree_complete(payload):
            prompt = (
                f"What grade did you finish {degree} with, on your "
                "institution's own scale? Give the mark and the scale "
                "together, for example 16.45/20.0."
            )
        else:
            prompt = (
                f"What is your grade so far in {degree}, or your expected "
                "classification, on your institution's own scale? For example "
                "15.8/20.0 to date, or '2.1 expected'."
            )
        questions.append(
            GapQuestion(
                kind=Kind.MISSING_GRADE,
                fact_id=fact.id,
                payload_key="grade_native",
                prompt=prompt,
                evidence=(
                    f"{degree}"
                    + (f" at {institution}" if institution else "")
                    + " is on file with no grade."
                ),
            )
        )
    return tuple(questions)


def _degree_complete(payload: dict[str, object]) -> bool:
    """Whether a degree's end date is in the past.

    No end date renders as "present" and is in progress; a future end date is
    an expected graduation and is in progress too. Only a past end date means a
    final grade can exist. The ledger stores dates as the CV printed them
    ("June 2024", "2024-06-30"), so parse_cv_date does the reading -- and an
    unparseable date is treated as complete, because asking for a final grade
    the student may not have is a recoverable wrong question, while asking a
    graduate for a "grade so far" reads as if we did not read their CV.
    """
    raw = payload.get("end_date")
    if not raw:
        return False
    end = parse_cv_date(raw)
    return end is None or end <= date.today()


def _most_recent_degree(facts: list[VerifiedFact]) -> VerifiedFact | None:
    """The degree that started last, or nothing.

    A degree with no readable start date is never the most recent: the answer
    would be whichever row the database returned first, which is not a fact
    about the student.
    """
    dated = [
        (start, fact)
        for fact in facts
        if isinstance(fact.payload, dict)
        and (start := _read_date(fact.payload.get("start_date"))) is not None
    ]
    if not dated:
        return None
    return max(dated, key=lambda pair: pair[0])[1]


def missing_degree_detail(student: Membership) -> tuple[GapQuestion, ...]:
    """What an education entry carries beyond the degree and the institution.

    S-040, from UCC's own list: "dates, qualification, supervisor,
    dissertation, papers and awards". Toronto's worked CV prints
    "Dissertation: ..." then "Supervisor: Dr. Carine Mendelsson" under the
    degree. We printed neither, because nothing ever asked.

    The thesis is asked of the MOST RECENT degree only. A bachelor's thesis on
    a CV whose master's is in progress is rarely what an admissions reader
    wants, and asking every degree turns one question into three for one fact
    a reader uses once.

    A rank is asked only of a COMPLETED degree that already has a grade. UCC
    wants the cohort size beside a foreign grade -- "interpret grades ...
    indicate range of scores and size of class" -- and US credential guidance
    calls a rank more telling than a converted GPA. But an in-progress student
    has no final rank, and a degree with no grade at all is already being
    asked for the grade by missing_grade; a second question about the same
    line is where a form starts feeling like an interrogation.
    """
    facts = _current(student, VerifiedFact.Category.EDUCATION)
    recent = _most_recent_degree(facts)
    questions: list[GapQuestion] = []
    for fact in facts:
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        degree = str(payload.get("degree_as_awarded") or "your degree")
        if fact is recent and not payload.get("thesis_title"):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_DEGREE_DETAIL,
                    fact_id=fact.id,
                    payload_key="thesis_title",
                    prompt=(
                        f"What is the title of your {degree} thesis or dissertation? "
                        "If it is not finished, give the working title."
                    ),
                    evidence=f"{degree} is on file with no thesis title.",
                )
            )
        if payload.get("thesis_title") and not payload.get("supervisor"):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_DEGREE_DETAIL,
                    fact_id=fact.id,
                    payload_key="supervisor",
                    prompt=f"Who supervised your {degree} thesis?",
                    evidence=(
                        f"{degree} states a thesis and names nobody who supervised it."
                    ),
                )
            )
        if (
            payload.get("grade_native")
            and not payload.get("class_rank")
            and _degree_complete(payload)
        ):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_DEGREE_DETAIL,
                    fact_id=fact.id,
                    payload_key="class_rank",
                    prompt=(
                        f"Where did you rank in your cohort for {degree}, if your "
                        "institution states it? For example '3rd of 120' or 'top 5%'. "
                        "Leave this blank if it was never published."
                    ),
                    evidence=(
                        f"{degree} has a grade and no rank; a reader abroad cannot tell "
                        "what that grade is worth without the cohort."
                    ),
                )
            )
    return tuple(questions)


def missing_medium_of_instruction(student: Membership) -> tuple[GapQuestion, ...]:
    """What language the student's highest COMPLETED degree was taught in.

    S-050's highest-value find and the one that promises nothing. Cornell, USC,
    BU and ASU all accept an English-taught degree in place of a test, and all
    on different terms, so this asks the fact and says nothing about a waiver:
    the prompt must not imply an exemption it cannot grant, because the layer
    that grants one reads a programme's page and this layer never does.

    Completed only. A degree still running has no certifiable medium yet, and a
    fourth-year applicant asked to produce one is being asked for a document
    their registrar will not issue.
    """
    completed = [
        fact
        for fact in _current(student, VerifiedFact.Category.EDUCATION)
        if _degree_complete(fact.payload if isinstance(fact.payload, dict) else {})
    ]
    highest = _most_recent_degree(completed)
    if highest is None:
        return ()
    payload = highest.payload if isinstance(highest.payload, dict) else {}
    if payload.get("medium_of_instruction"):
        return ()
    degree = str(payload.get("degree_as_awarded") or "your degree")
    return (
        GapQuestion(
            kind=Kind.MEDIUM_OF_INSTRUCTION,
            fact_id=highest.id,
            payload_key="medium_of_instruction",
            prompt=(
                f"What language was {degree} taught in, and can your university "
                "issue a letter confirming it? Several universities ask for this in "
                "writing; what they do with it differs, so we record what yours says."
            ),
            evidence=f"{degree} is on file with no language of instruction.",
        ),
    )


def missing_award(student: Membership) -> tuple[GapQuestion, ...]:
    """Money awarded on merit that the CV never mentioned, and every award
    already on file that names nobody who gave it.

    Two questions on one subject, sharing Kind.MISSING_AWARD: from the
    student's side, "did you ever get an award" and "who gave you this one"
    are the same topic.

    Owner observation 2026-09-15, from reading what real applicants put in this
    section: a scholarship, a stipend, even "10% tuition reduction for academic
    merit" belongs in Awards, and students routinely leave it out because it
    reads to them as a fee arrangement rather than an honour. It is neither --
    it is a competitive selection someone else made about them, which is
    exactly what an admissions reader is looking for. UCC says what to record
    once it is there: "State funding body, terms, duration and amount", and
    "Awards or any funding secured merit serious consideration".

    The first question fires when no award on file carries a `detail`, which
    is the field that holds those terms (S-035). That is deliberately NOT a
    keyword test over award titles: `_is_research_applicant` below records why
    this module does not classify strings, and a money-word list would be
    English-shaped in a product whose applicants are not. The cost of the
    cruder rule is that a student who has recorded a scholarship without its
    terms is asked anyway -- and the prompt answers that case too, by asking
    for the terms. It is the only question here with no fact to supersede: an
    award the CV never mentioned is a new row, not a correction.

    The second is per award rather than one question for the section: which
    one is missing a body (S-035) is the whole content of the question.
    Toronto prints "Instructor of the Year" over "Doctor of Pharmacy program,
    University of Toronto"; Berkeley bolds "Chancellor's Fellowship ..., UC
    Berkeley". AwardEntry has held the field since 2026-09-15 and nothing ever
    asked for it, so every award generated from a CV that did not print one
    stays anonymous. Distinct from the first question, which asks whether an
    award exists at all -- this one corrects an award already on file.
    """
    # An empty ledger asks nothing at all. Every other detector here is
    # null-checking rows that exist, so it inherits that for free; this one
    # fires on ABSENCE and would otherwise ask a student who has uploaded
    # nothing about a CV that does not exist.
    if not unsuperseded_facts(student).exists():
        return ()
    awards = _current(student, VerifiedFact.Category.AWARD)
    if any((fact.payload or {}).get("detail") for fact in awards if isinstance(fact.payload, dict)):
        create_questions: tuple[GapQuestion, ...] = ()
    else:
        listed = len(awards)
        evidence = (
            f"Your CV lists {listed} award(s), none with an amount or terms."
            if listed
            else "Your CV lists no awards."
        )
        create_questions = _group_questions("merit-award", Kind.MISSING_AWARD, evidence)
    detail_questions = tuple(
        GapQuestion(
            kind=Kind.MISSING_AWARD,
            fact_id=fact.id,
            payload_key="awarding_body",
            prompt=(
                f'Who awarded "{title}" -- which faculty, institution or funding body?'
            ),
            evidence=f'"{title}" is on file with nobody named as the awarding body.',
        )
        for fact in awards
        if isinstance(fact.payload, dict)
        and not fact.payload.get("awarding_body")
        and (title := str(fact.payload.get("title") or "an award on your CV"))
    )
    return create_questions + detail_questions


def _is_research_applicant(student: Membership) -> bool:
    """Whether this student's posts plausibly had principal investigators.

    D2: the design doc says "an academic-looking employer", which implies a
    keyword list over employer strings. Such a list has to recognise CNRS,
    Max-Planck-Institut and Institut Curie and will still miss the next one,
    and it is English-shaped in a product whose applicants are not. The
    student's own ledger answers the same question without a list.
    """
    return (
        unsuperseded_facts(student)
        .filter(
            category__in=(
                VerifiedFact.Category.RESEARCH,
                VerifiedFact.Category.PUBLICATION,
            )
        )
        .exists()
    )


def incomplete_entry(student: Membership) -> tuple[GapQuestion, ...]:
    """A section missing a field the reader needs.

    S-028: an academic post names the group or laboratory and its principal
    investigator; an industry post names the company; both carry a month-year
    range.

    The doc's third detector -- "any entry with no end_date and no 'present'"
    -- describes a state this schema cannot hold: end_date=None *is* present,
    rendered by every template as |month_year:"present". There is no separate
    flag to be missing. What is genuinely ambiguous is whether the CV meant
    "still running" or simply omitted the date, so that is what gets asked.
    """
    questions: list[GapQuestion] = []
    ask_supervisor = _is_research_applicant(student)
    for fact in _current(student, VerifiedFact.Category.EXPERIENCE):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        employer = str(payload.get("employer") or "a post on your CV")
        title = str(payload.get("title") or "")
        where = f"{title} at {employer}" if title else employer
        if ask_supervisor and not payload.get("supervisor"):
            questions.append(
                GapQuestion(
                    kind=Kind.INCOMPLETE_ENTRY,
                    fact_id=fact.id,
                    payload_key="supervisor",
                    prompt=f"Who supervised your work as {where}?",
                    evidence=(
                        f"{where} names no supervisor, and your CV lists research work."
                    ),
                )
            )
        if not payload.get("end_date"):
            questions.append(
                GapQuestion(
                    kind=Kind.INCOMPLETE_ENTRY,
                    fact_id=fact.id,
                    payload_key="end_date",
                    prompt=f"Are you still working as {where}? If not, when did it end?",
                    evidence=f"{where} has a start date and no end date.",
                )
            )
    # R-040 (cv-rules.csv, BINDING, universal): an in-progress degree states
    # its expected graduation date. end_date=None renders as "present", which
    # is true and useless on a document whose whole purpose is applying while
    # still enrolled -- measured on a real CV, where a master's read
    # "Sep 2024 - present" and no reader could tell when it finishes. The
    # renderer already prints a future end_date; nothing ever put one there.
    #
    # Asked, not inferred: a nominal two-year programme does not tell us when
    # THIS student finishes, and a date nobody stated is the claim this whole
    # ledger exists to refuse.
    for fact in _current(student, VerifiedFact.Category.EDUCATION):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        if payload.get("end_date") or not payload.get("start_date"):
            continue
        degree = str(payload.get("degree_as_awarded") or "your degree")
        questions.append(
            GapQuestion(
                kind=Kind.INCOMPLETE_ENTRY,
                fact_id=fact.id,
                payload_key="end_date",
                prompt=(
                    f"When do you expect to finish {degree}? "
                    "Give the month and year, or the date you finished if it is done."
                ),
                evidence=f"{degree} has a start date and no end date, so it prints as 'present'.",
            )
        )
    for fact in _current(student, VerifiedFact.Category.RESEARCH):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        if payload.get("institution"):
            continue
        thesis = str(payload.get("thesis_title") or "your research")
        questions.append(
            GapQuestion(
                kind=Kind.INCOMPLETE_ENTRY,
                fact_id=fact.id,
                payload_key="institution",
                prompt=f"Where did you carry out {thesis}?",
                evidence=f"{thesis} names no institution.",
            )
        )
    return tuple(questions)


def missing_publication_detail(student: Membership) -> tuple[GapQuestion, ...]:
    """A citation a reader cannot resolve, place or attribute.

    S-011 asks for a resolvable DOI, the applicant's own name bolded and author
    order preserved. Two of the three need a field the extractor often cannot
    fill: a DOI is not on every CV, and which position in a byline is the
    applicant is something only they know when the surname repeats.

    The answer to the authorship question lands in self_author_index as the
    student typed it. PublicationEntry's own validator refuses an index that
    does not point at one of the authors when a draft is built, which is the
    right place for that check -- the ledger records the claim, the schema
    refuses the document.
    """
    questions: list[GapQuestion] = []
    for fact in _current(student, VerifiedFact.Category.PUBLICATION):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        title = str(payload.get("title") or "a publication on your CV")
        if not payload.get("doi") and not payload.get("url"):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_PUBLICATION_DETAIL,
                    fact_id=fact.id,
                    payload_key="doi",
                    prompt=(
                        f'Does "{title}" have a DOI? If not, is there a landing page '
                        "for it?"
                    ),
                    evidence=(
                        f'"{title}" has neither a DOI nor an address, so a reader '
                        "cannot find it."
                    ),
                )
            )
        if payload.get("self_author_index") is None:
            authors = payload.get("authors")
            byline = (
                ", ".join(str(name) for name in authors)
                if isinstance(authors, list)
                else ""
            )
            evidence = (
                f'The byline on "{title}" is: {byline}. We cannot tell which name '
                "is yours, so none is emphasised."
                if byline
                else f'"{title}" lists no authors we can match you against.'
            )
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_PUBLICATION_DETAIL,
                    fact_id=fact.id,
                    payload_key="self_author_index",
                    prompt=(
                        f'Which author are you on "{title}"? Give the position -- 1 '
                        "for first author, 2 for second, and so on."
                    ),
                    evidence=evidence,
                )
            )
        if not payload.get("year"):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_PUBLICATION_DETAIL,
                    fact_id=fact.id,
                    payload_key="year",
                    prompt=f'What year was "{title}" published?',
                    evidence=f'"{title}" is on file with no year.',
                )
            )
    return tuple(questions)


def absent_sections(student: Membership) -> tuple[GapQuestion, ...]:
    """Questions about what the ledger holds no facts of at all.

    Nothing in a document reveals what it does not mention, so these fire on
    ABSENCE and would otherwise ask a student who has uploaded nothing about a
    CV that does not exist -- the same guard missing_award carries, for the
    same reason.

    Voluntary work is asked of ANY non-empty ledger, deliberately not gated on
    a country, UNTIL IT HAS BEEN ANSWERED ONCE. Searched 2026-09-15: no
    country's guidance was found that excludes voluntary or community activity
    from an admissions CV, and it is named positively in the UK, Netherlands,
    France, Germany, Ireland and the US (S-042). A gate returning "ask" in
    every case there is evidence for is a table that does nothing -- but
    "unconditionally" used to mean "every page load, forever": the guard here
    used to be ``not any(fact.payload.get("unpaid") ...)``, which can never be
    true, because ``unpaid`` is a field on ``ExperienceEntry`` (schemas.py)
    that ``_PAYLOAD_KEYS[EXPERIENCE]`` (verification.py) never carries, so no
    fact payload in this ledger has ever held that key. A created voluntary
    role is an ordinary EXPERIENCE row -- an employer, a title, a bullet, same
    as a job -- so it satisfied the guard's `unpaid` test exactly as poorly as
    every job the student never marked voluntary, and the question re-fired on
    every subsequent page load. ``_already_created`` replaces it with the
    stamp ``answer_questions`` puts on its own writes, same mechanism as
    ``profile_bridge.py``.

    Three questions for one role, not one: an ExperienceEntry needs an
    employer, a title and at least one bullet, so a single free-text answer
    builds a fact generation cannot turn into an entry. They share a slug, so
    answer_questions writes them as one fact and writes nothing if the
    student answers only part (see that function).

    Referees are asked of a research-track applicant only (R-051), judged by
    _is_research_applicant -- the student's own ledger, never a keyword list
    over employer strings -- and, like voluntary work, only until answered
    once.
    """
    if not unsuperseded_facts(student).exists():
        return ()
    questions: list[GapQuestion] = []
    if not _already_created(student, "voluntary-role"):
        questions.extend(
            _group_questions(
                "voluntary-role",
                Kind.ABSENT_SECTION,
                "Your CV lists no voluntary or community activity. Oxford makes it one of "
                "three headings, and the Swedish Institute requires it.",
            )
        )
    if (
        _is_research_applicant(student)
        and not _current(student, VerifiedFact.Category.REFERENCE)
        and not _already_created(student, "referee")
    ):
        questions.extend(
            _group_questions(
                "referee",
                Kind.ABSENT_SECTION,
                "Your CV names no referee, and European research applications "
                "routinely expect one.",
            )
        )
    return tuple(questions)


def education_completeness(student: Membership) -> tuple[GapQuestion, ...]:
    """Study and roles the student has, and never thought to write down.

    ETH, verbatim: list "every university attended, including any mobility or
    exchange programmes and study programmes which were not completed." ETH
    treats the omission as the applicant's fault, and neither an Erasmus
    semester nor an abandoned programme is a thing anyone volunteers -- the
    first reads as not a real degree, the second as a failure.

    Also the society/committee role Toronto Mississauga's checklist,
    Cambridge and the Harvard Kennedy School all ask for. S-039 still refuses
    a memberships SECTION; as a question it is one line and the answer is an
    ordinary ExperienceEntry, which is where a role with responsibilities
    belongs.

    Fired on any non-empty ledger, same guard as absent_sections and for the
    same reason: nothing in a ledger built from the student's own CV can
    reveal a degree the CV never mentioned. Each of the three groups is
    gated separately by ``_already_created`` -- like voluntary-role and
    referee, a created group is an ordinary EDUCATION or EXPERIENCE row once
    it lands, so the source_ref stamp is the only thing that stops it
    re-firing forever once answered.

    Two questions per programme because an EducationEntry needs an
    institution AND a degree title, and they share a slug so
    answer_questions writes one fact. A society role needs three, like a
    voluntary one.
    """
    if not unsuperseded_facts(student).exists():
        return ()
    eth = (
        "ETH Zurich asks for every university attended, including exchange "
        "programmes and programmes that were not completed."
    )
    society = (
        "Toronto, Cambridge and the Harvard Kennedy School all ask for positions "
        "held in student societies and committees."
    )
    questions: list[GapQuestion] = []
    for slug, evidence in (
        ("exchange-programme", eth),
        ("unfinished-programme", eth),
        ("society-role", society),
    ):
        if not _already_created(student, slug):
            questions.extend(_group_questions(slug, Kind.EDUCATION_COMPLETENESS, evidence))
    return tuple(questions)


def programme_required(student: Membership, programme: Program) -> tuple[GapQuestion, ...]:
    """One question per (include directive, fact) where the fact lacks the field.

    Only a key the category carries is asked (payload_keys): answer_questions
    refuses anything else, and a question nobody can answer is worse than
    none. The page's sentence goes in `evidence`, labelled as the programme's
    request -- it is context for the student, never an instruction to them.
    """
    questions: list[GapQuestion] = []
    for directive in directives_from_program(programme):
        if directive.action != "include":
            continue
        section, _, field = directive.target.partition(".")
        category = _TARGET_CATEGORY.get(section)
        if category is None or field not in payload_keys(category):
            continue
        for fact in _current(student, category):
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            if payload.get(field) not in (None, ""):
                continue
            label = str(
                payload.get("degree_as_awarded")
                or payload.get("title")
                or payload.get("full_name")
                or "this entry"
            )
            questions.append(
                GapQuestion(
                    kind=Kind.PROGRAMME_REQUIRED,
                    fact_id=fact.id,
                    payload_key=field,
                    prompt=f"What is the {field.replace('_', ' ')} for {label}?",
                    evidence=f"{programme.name} asks: {directive.rule_text}",
                )
            )
    return tuple(questions)


class UnanswerableQuestion(ValueError):
    """An answer cannot be written: wrong student, wrong key, or a fact whose
    tier a typed sentence may not overwrite.

    Not raised for a blank answer -- every question is skippable, and a skip is
    an ordinary outcome rather than an error.
    """


#: Payload keys whose schema type is a sequence, so a typed answer is stored
#: as a one-element list rather than a bare string. Without this a voluntary
#: role's bullet reached the ledger as a string while every ingested
#: experience carries a list (verification.fact_payload builds it from
#: ExperienceEntry.bullets, a tuple), and generation._facts_payload puts both
#: shapes in front of the model under one key.
_LIST_KEYS = frozenset({"bullets"})


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


@transaction.atomic
def answer_questions(
    answers: Sequence[tuple[GapQuestion, str]], *, student: Membership
) -> tuple[VerifiedFact, ...]:
    """Write a form's worth of answers as superseding candidate facts.

    One row per fact, carrying every answer for that fact. Written one at a
    time instead, the first answer would supersede the fact the second names
    and the second would be refused as stale -- a post missing both its
    supervisor and its end date produces exactly that pair.

    A correction is a new row with supersedes set: the ledger is append-only
    (see VerifiedFact's docstring), so this never mutates the row it answers.
    Everything written is a candidate -- confirmed_by=None, exactly as
    ingest_uploaded_cv writes -- and generation reads generatable_facts, so an
    answer cannot reach a document until a counsellor accepts it.

    Blank answers are dropped: a skipped question is not an empty fact, and a
    form of blanks writes nothing at all. Everything else that fails raises,
    and the whole batch is one transaction -- a student who answered three
    questions and tripped a guard on the fourth must not find two of them
    landed. All three guards read values that arrived from a form, which makes
    them a trust boundary rather than a hint.

    A double submit cannot fork the chain, and the guard is the
    ``verifiedfact_one_superseder`` index rather than anything here. Two
    concurrent batches both read the tip as current -- a row lock does not stop
    that, because the fork comes from INSERTing a sibling rather than modifying
    the locked row, so under READ COMMITTED the loser's anti-join never sees
    the winner (measured, not argued: see that constraint's comment). The
    index refuses the second write, and the loser is told its answers did not
    land, which is true and is what the form re-renders.
    """
    updates: dict[UUID, dict[str, str]] = {}
    # slug -> (one question of that group, the answers given). A new entry
    # takes several answers -- an EducationEntry needs an institution AND a
    # degree, an ExperienceEntry an employer, a title and a bullet -- so the
    # group is the unit of creation, not the question. The question is kept
    # because it carries the group's category, its full key list and its
    # defaults; all three are server-built and identical across the group.
    creations: dict[str, tuple[GapQuestion, dict[str, str]]] = {}
    for question, answer in answers:
        value = answer.strip()
        if not value:
            continue
        if question.fact_id is None:
            # A question about something the ledger does not hold: the answer
            # is a new fact, not a correction. `category` comes off the
            # server-built question, never off the form.
            if question.category is None:
                raise UnanswerableQuestion("a question with no fact must name a category")
            # The ledger stores whatever string it is handed, and generation
            # validates TimelineEntry.statement against TIMELINE_STATEMENT_MAX:
            # an over-long answer accepted here is a fact that makes every
            # later CV for this student fail. Refused at the door instead,
            # which the form already shows as an error. The schema also refuses
            # it below; this stays for the message, which a student can act on.
            if (
                question.category == VerifiedFact.Category.TIMELINE
                and len(value) > TIMELINE_STATEMENT_MAX
            ):
                raise UnanswerableQuestion(
                    f"keep it to {TIMELINE_STATEMENT_MAX} characters"
                )
            slug = question.slug
            assert slug is not None  # GapQuestion.__post_init__ guarantees it
            first, fields = creations.setdefault(slug, (question, {}))
            if first.category != question.category:
                raise UnanswerableQuestion(f"{slug} names two categories")
            if first.group_keys != question.group_keys:
                raise UnanswerableQuestion(f"{slug} declares two key sets")
            fields[question.payload_key] = value
            continue
        updates.setdefault(question.fact_id, {})[question.payload_key] = value
    if not updates and not creations:
        return ()

    written: list[VerifiedFact] = []
    for slug, (question, fields) in creations.items():
        # All or nothing. A half-answered group writes a fact no reader can use
        # -- an EDUCATION row holding an institution and no degree gives
        # generation nothing to build an entry from, and the model's only legal
        # move is to invent the other half. A dropped partial answer costs one
        # re-ask, which the interview does on its own because the detector
        # still fires.
        if set(fields) != set(question.group_keys):
            continue
        category = question.category
        assert category is not None  # checked when the answer was read
        # Merged after the completeness check above: a default is not
        # something the student answered, and must not count toward it.
        full_fields: dict[str, object] = {**fields, **dict(question.defaults)}
        unknown = sorted(set(full_fields) - set(payload_keys(category)))
        if unknown:
            raise UnanswerableQuestion(f"{category} facts do not carry {', '.join(unknown)}")
        if category == VerifiedFact.Category.TIMELINE:
            # Through the entry generation builds from it, so the ledger holds
            # what the CV prints: the statement tidied as the schema tidies it,
            # the dates as the schema writes them, and no end_date at all for
            # the trailing gap. Stored raw, a tidied CV line disagrees with its
            # own fact.
            try:
                entry = TimelineEntry.model_validate(full_fields)
            except ValidationError:
                # `from None`, not `from error`: a ValidationError carries the
                # rejected input, and a gap answer is health or family data
                # more often than not (approval.py, same choice, same reason).
                raise UnanswerableQuestion(
                    f"{slug}: that answer cannot be printed on the CV"
                ) from None
            full_fields = entry.model_dump(mode="json", exclude_none=True)
        payload = {
            key: [value] if key in _LIST_KEYS else value
            for key, value in full_fields.items()
        }
        written.append(
            VerifiedFact.objects.create(
                student=student,
                category=category,
                payload=payload,
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                # Prefixed with the slug, unlike the supersede path below: a
                # created fact is otherwise indistinguishable from any other
                # row once it lands (a voluntary role is an EXPERIENCE row
                # with an employer, a title and a bullet, exactly like a job),
                # so this stamp is the only thing that can say "this group was
                # already answered" -- see _already_created. Same mechanism
                # as profile_bridge.py's own source_ref prefix.
                source_ref=f"gap-interview:{slug}",
                confirmed_by=None,
                supersedes=None,
                created_by=student,
            )
        )
    for fact_id, fields in updates.items():
        target = unsuperseded_facts(student).filter(id=fact_id).first()
        if target is None:
            raise UnanswerableQuestion(f"no current fact {fact_id} for this student")
        if target.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT:
            raise UnanswerableQuestion("an authoritative fact cannot be answered over")
        allowed = payload_keys(target.category)
        unknown = sorted(set(fields) - set(allowed))
        if unknown:
            raise UnanswerableQuestion(
                f"{target.category} facts do not carry {', '.join(unknown)}"
            )
        payload = dict(target.payload) if isinstance(target.payload, dict) else {}
        try:
            created = VerifiedFact.objects.create(
                student=student,
                category=target.category,
                payload={**payload, **fields},
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref="gap-interview",
                confirmed_by=None,
                supersedes=target,
                created_by=student,
            )
        except IntegrityError as error:
            # verifiedfact_one_superseder: someone else answered this same
            # question between our read and our write. Their row is the tip
            # now, so ours is not a correction to apply -- it is an answer to
            # a question that no longer exists, which is what this exception
            # already means everywhere else it is raised.
            raise UnanswerableQuestion(f"fact {fact_id} was answered concurrently") from error
        written.append(created)
    return tuple(written)


def gap_questions(
    student: Membership, programme: Program | None = None
) -> tuple[GapQuestion, ...]:
    """Everything the ledger can be asked about without a model call.

    Ordered by value, highest first, and the order is the only thing spent: a
    contact line and a language certificate come before a publication's year,
    so a student who stops a third of the way down has answered the questions
    every destination asks. There is no cap, deliberately -- a dropped question
    is a fact the ledger never gets and nothing ever asks for again, which is
    the silent failure this repo keeps recording.

    Deliberately whole-ledger and one-shot rather than a conversation: these
    questions are independent of each other, the student sees one form, and a
    chat loop would cost a call per turn to produce the same questions in a
    worse order.

    With a programme, its own `include` requirements are asked last -- they
    are the most specific and the least likely to be answerable from memory.
    """
    questions = (
        missing_contact(student)
        + missing_language_detail(student)
        + timeline_gaps(student)
        + missing_medium_of_instruction(student)
        + missing_grade(student)
        + missing_degree_detail(student)
        + incomplete_entry(student)
        + missing_publication_detail(student)
        + missing_award(student)
        + absent_sections(student)
        + education_completeness(student)
    )
    if programme is not None:
        questions += programme_required(student, programme)
    return questions
