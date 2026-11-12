"""Requirement detectors: missing language details, awards, incomplete entries,
publication details, absent sections, and programme/upper-secondary requirements.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from apps.documents.constraints import ConstraintRule, PageDirective, directives_from_program
from apps.documents.gaps.models import (
    _TARGET_CATEGORY,
    GapQuestion,
    Kind,
    _already_created,
    _current,
    _cv_on_file,
    _group_questions,
)
from apps.documents.models import VerifiedFact
from apps.documents.verification import has_full_name, payload_keys, unsuperseded_facts
from apps.funding.models import Program
from apps.tenancy.models import Membership

logger = logging.getLogger(__name__)


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
    if not _cv_on_file(student):
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
    if not _cv_on_file(student):
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
    from apps.documents.models import Referee

    if (
        _is_research_applicant(student)
        and not _current(student, VerifiedFact.Category.REFERENCE)
        and not Referee.objects.filter(student=student, status=Referee.Status.ACTIVE).exists()
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


def _upper_secondary_from_rules(
    student: Membership, rules: Iterable[ConstraintRule], programme_name: str
) -> tuple[GapQuestion, ...]:
    from apps.documents.coverage import coverage_of, is_secondary
    from apps.documents.schemas import EducationEntry

    rule_tuple = tuple(rules)
    if coverage_of(rule_tuple).start != "upper_secondary":
        return ()
    for fact in _current(student, VerifiedFact.Category.EDUCATION):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        degree = str(payload.get("degree_as_awarded") or "")
        institution = str(payload.get("institution_original") or "")
        if degree and institution and is_secondary(
            EducationEntry(degree_as_awarded=degree, institution_original=institution)
        ):
            return ()
    if _already_created(student, "upper-secondary"):
        return ()
    sentence = next(r.rule_text for r in rule_tuple if r.key == "cv_start")
    return _group_questions(
        "upper-secondary", Kind.PROGRAMME_REQUIRED, f"{programme_name} asks: {sentence}"
    )


def upper_secondary_required(student: Membership, programme: Program) -> tuple[GapQuestion, ...]:
    """Spec §8: a page asking the CV to begin at school (ETH: "Begin with your
    UPPER SECONDARY SCHOOL GRADUATION") needs a school-leaving entry. It is
    asked for, never invented; render._check_cv_start warns until it exists."""
    from types import SimpleNamespace

    from apps.documents.constraints import resolve_rules

    rules = resolve_rules(programme, None, content=SimpleNamespace(research=()))
    return _upper_secondary_from_rules(student, rules, programme.name)


def _programme_directives_questions(
    student: Membership, directives: Iterable[PageDirective], programme_name: str
) -> tuple[GapQuestion, ...]:
    from apps.portals.profile import verified_values

    questions: list[GapQuestion] = []
    held: dict[str, str] | None = None
    for directive in directives:
        if directive.action != "include":
            continue
        section, _, field = directive.target.partition(".")
        category = _TARGET_CATEGORY.get(section)
        if category is None or field not in payload_keys(category):
            continue
        if category == VerifiedFact.Category.IDENTITY:
            # The person is one: a value a portal already gets (a passport's
            # proven date of birth) is never asked again. A repeated category's
            # flattened key is only its last row, so it says nothing per fact.
            held = verified_values(student) if held is None else held
            if f"identity.{field}" in held:
                continue
        facts = (
            # A passport read writes one IDENTITY row per key; only the named
            # row is "the person" a question can be about.
            list(has_full_name(unsuperseded_facts(student)))
            if category == VerifiedFact.Category.IDENTITY
            else _current(student, category)
        )
        for fact in facts:
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
                    evidence=f"{programme_name} asks: {directive.rule_text}",
                )
            )
    return tuple(questions)


def programme_required(student: Membership, programme: Program) -> tuple[GapQuestion, ...]:
    """One question per (include directive, fact) where the fact lacks the field.

    Only a key the category carries is asked (payload_keys): answer_questions
    refuses anything else, and a question nobody can answer is worse than
    none. The page's sentence goes in `evidence`, labelled as the programme's
    request -- it is context for the student, never an instruction to them.
    """
    return _programme_directives_questions(
        student, directives_from_program(programme), programme.name
    )


def _active_draft_programme_questions(student: Membership) -> tuple[GapQuestion, ...]:
    """Surface `PROGRAMME_REQUIRED` questions from the student's active CV drafts'
    saved `RequirementList`s without touching the shared catalogue (`runtime_web` safe)."""
    from pydantic import ValidationError

    from apps.documents.models import DocumentDraft
    from apps.documents.requirement_list import RequirementList
    from apps.portals.models import Application

    closed_app_ids = set(
        (
            Application.objects.filter(
                student=student,
                state__in=(Application.State.SUBMITTED, Application.State.CONFIRMED),
            )
            | Application.objects.filter(student=student).exclude(outcome="")
        ).values_list("id", flat=True)
    )
    drafts = (
        DocumentDraft.objects.filter(
            student=student,
            kind=DocumentDraft.Kind.CV,
            requirements__isnull=False,
        )
        .exclude(status=DocumentDraft.Status.SUPERSEDED)
        .order_by("version")
    )
    seen: set[tuple[object, str]] = set()
    collected: list[GapQuestion] = []
    for draft in drafts:
        if draft.application_id is not None and draft.application_id in closed_app_ids:
            continue
        try:
            req_list = RequirementList.model_validate(draft.requirements)
        except ValidationError as error:
            logger.warning(
                "GapDraftRequirementsInvalid draft=%s errors=%d",
                draft.id,
                error.error_count(),
            )
            continue
        label = (draft.destination_label or "").strip() or "Your programme"
        candidates = _upper_secondary_from_rules(
            student, req_list.cv_rules(), label
        ) + _programme_directives_questions(student, req_list.cv_directives(), label)
        for q in candidates:
            key = (q.fact_id or q.slug, q.payload_key)
            if key not in seen:
                seen.add(key)
                collected.append(q)
    return tuple(collected)
