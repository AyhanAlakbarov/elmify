"""Deterministic letter gates I: claim coverage, wrong institution, and unanswered
prompt questions. These gates catch the complementary failure to the provenance
check in `letter_verification.py` -- text that asserts something without
declaring it as a `LetterClaim` at all, a letter addressed to the wrong
institution, and a prompt question the letter never answered.

Task 7 appends four more checks plus three amendment checks and a
`run_letter_gates` runner to this same module, extending `GateCode` with its
own new members rather than redefining it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .letter_schemas import ClaimKind, LetterContent, LetterUnit, Storyline


class GateCode(StrEnum):
    UNDECLARED_ASSERTION = "UNDECLARED_ASSERTION"
    WRONG_INSTITUTION = "WRONG_INSTITUTION"
    PROMPT_REQUIREMENT_UNMET = "PROMPT_REQUIREMENT_UNMET"
    DUPLICATES_PAIRED_DOCUMENT = "DUPLICATES_PAIRED_DOCUMENT"
    HEADER_BLOCK_MISSING = "HEADER_BLOCK_MISSING"
    LANGUAGE_MISMATCH = "LANGUAGE_MISMATCH"
    GENERIC_PARAGRAPH = "GENERIC_PARAGRAPH"
    # 2026-09-14 amendment (docs/research/2026-09-14-letter-storytelling-evidence.md §3)
    DUPLICATES_SIBLING_ANSWER = "DUPLICATES_SIBLING_ANSWER"
    FIRST_PERSON_PLURAL = "FIRST_PERSON_PLURAL"
    STORYLINE_DRIFT = "STORYLINE_DRIFT"
    #: Task 9. The page forbids naming and the letter named someone.
    NAMING_FORBIDDEN = "NAMING_FORBIDDEN"


@dataclass(frozen=True)
class LetterGateViolation:
    code: GateCode
    detail: str
    unit_archetype: str | None = None


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_DIGIT_PATTERN = re.compile(r"\d")
_DATE_PATTERN = re.compile(
    r"\b(19|20)\d{2}\b|\b\d{1,2}/\d{1,2}(/\d{2,4})?\b|\b(January|February|March|April|May|June|"
    r"July|August|September|October|November|December)\b"
)
#: Words and single punctuation marks. A word may carry a hyphen or an
#: apostrophe (Roe-Smith, O'Neill) and any Unicode letter: the old pattern was
#: `[A-Z][a-z]+|[A-Z]{2,}`, which could not see Müller, Şahin or Løvås -- the
#: normal shape of a supervisor's name in this catalog (Task 9 review).
_TOKEN = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*|[^\w\s]")

#: Lowercase words that CONTINUE a proper-noun run when a capitalised word
#: follows. "Technical University of Munich" and "Institute for Artificial
#: Intelligence" are one name each; breaking at `of` yielded "Technical
#: University", which matched no institution this catalog holds.
_CONNECTORS = frozenset(
    {"of", "for", "and", "the", "de", "del", "della", "di", "du", "des", "der", "van", "von", "zu"}
)
#: Dropped from the FRONT of a run, so a sentence that opens "The University
#: welcomes ..." does not make "The University" a name (Task 9 review: it
#: blocked a letter for saying "The University I attended taught me").
_LEADING_ARTICLES = frozenset({"the", "a", "an"})


def capitalised_phrases(text: str, *, minimum_words: int = 2) -> list[str]:
    """Runs of capitalised words, whitespace-normalised.

    A run is the proper-noun unit this module reasons about -- an acronym-led
    name ("TU Munich") counts, because it asserts a proper noun just as much
    as "Example University" does. Normalising the whitespace is what lets a
    name survive the line break model prose puts in the middle of it.
    """
    phrases: list[str] = []
    run: list[str] = []
    pending: list[str] = []
    for match in _TOKEN.finditer(text):
        part = match.group()
        if not part[:1].isalpha():
            if part == "." and run and run[-1].casefold() in _PERSON_TITLES:
                # An abbreviated title is part of the name, not the end of a
                # sentence: "Prof. Dr. Jane Roe" closed three runs of one word
                # each and guarded nothing, and that is the dominant German
                # form (PR review, 2026-09-22). Only a title abbreviates this
                # way, so a sentence that really ends cannot glue itself to the
                # next one.
                run[-1] = f"{run[-1]}."
                continue
            run, pending = _close(run, pending, phrases, minimum_words), []
            continue
        if part[:1].isupper():
            run.extend(pending)
            pending = []
            run.append(part)
        elif run and part.casefold() in _CONNECTORS:
            pending.append(part)
        else:
            run, pending = _close(run, pending, phrases, minimum_words), []
    _close(run, pending, phrases, minimum_words)
    return phrases


def _close(
    run: list[str], pending: list[str], phrases: list[str], minimum_words: int
) -> list[str]:
    while run and run[0].casefold() in _LEADING_ARTICLES:
        run = run[1:]
    if len(run) >= minimum_words:
        phrases.append(" ".join(run))
    return []


#: Only a claim kind that carries provenance -- an id a caller can actually
#: check -- may satisfy check_claim_coverage's requirement that a triggering
#: sentence be covered. INTERPRETIVE and ASPIRATIONAL claims carry no id "by
#: design" (letter_verification.py's _classify auto-SUPPORTS both, precisely
#: because there is nothing to verify); letting either kind cover a sentence
#: with a proper noun or a date would let a fabricated factual claim clear
#: this gate just by being mislabelled. This must match (or be a subset of)
#: letter_verification.py's own provenance-bearing kinds.
_PROVENANCE_CLAIM_KINDS = frozenset({ClaimKind.FACTUAL, ClaimKind.DECLARED, ClaimKind.SOURCED})


def _has_trigger(sentence: str) -> bool:
    return bool(
        _DIGIT_PATTERN.search(sentence)
        or _DATE_PATTERN.search(sentence)
        or bool(capitalised_phrases(sentence))
    )


def sentence_spans(text: str) -> list[tuple[str, int, int]]:
    """Split ``text`` into sentences with their ``[start, end)`` offsets.

    Public, and shared with ``letter_render.hygienic_letter_content``'s
    claim-span re-anchoring on purpose: that function has to reproduce this
    walk exactly -- the same regex *and* the same cursor-advancing
    ``index()`` search, so a sentence repeated verbatim inside one unit
    anchors to the right occurrence in both places. Two copies of "split on
    _SENTENCE_SPLIT" that drift by one character put the gate and the
    re-anchoring back out of agreement, which is the defect this helper
    exists to make impossible.
    """
    spans: list[tuple[str, int, int]] = []
    cursor = 0
    for sentence in _SENTENCE_SPLIT.split(text):
        start = text.index(sentence, cursor)
        end = start + len(sentence)
        cursor = end
        spans.append((sentence, start, end))
    return spans


def check_claim_coverage(unit: LetterUnit) -> tuple[LetterGateViolation, ...]:
    violations: list[LetterGateViolation] = []
    for sentence, start, end in sentence_spans(unit.text):
        if not _has_trigger(sentence):
            continue
        covered = any(
            claim.span_start <= start and claim.span_end >= end
            for claim in unit.claims
            if claim.kind in _PROVENANCE_CLAIM_KINDS
        )
        if not covered:
            violations.append(
                LetterGateViolation(GateCode.UNDECLARED_ASSERTION, sentence.strip(), unit.archetype)
            )
    return tuple(violations)


def check_wrong_institution(
    content: LetterContent, *, forbidden_names: frozenset[str]
) -> tuple[LetterGateViolation, ...]:
    violations = []
    for unit in content.units:
        for name in forbidden_names:
            if name in unit.text:
                violations.append(
                    LetterGateViolation(
                        GateCode.WRONG_INSTITUTION, f"mentions {name!r}", unit.archetype
                    )
                )
    return tuple(violations)


#: A phrase is a PERSON when it opens with a title, and a GROUP when one of
#: its words names a body. This is the whole test for whether something read
#: off a programme's page is a name at all -- see `names_worth_guarding`.
_PERSON_TITLES = frozenset(
    {"professor", "prof", "dr", "doctor", "mr", "ms", "mrs", "miss", "sir", "dame", "herr", "frau"}
)
_GROUP_WORDS = frozenset(
    {
        "lab", "laboratory", "labor", "group", "institute", "institut", "centre", "center",
        "chair", "department", "faculty", "school", "unit", "cluster", "college", "division",
    }
)


def names_worth_guarding(text: str) -> set[str]:
    """The phrases in `text` that could name a person, group or lab.

    NOT every proper noun, which is what the first version of this gate took
    from a programme's statements. Measured on four realistic
    `ProgramStatement` rows (Task 9 review), that harvested "Curriculum
    Vitae", "Motivation Letter", "Winter Semester" and "English Language" --
    so an ordinary letter saying "I enclose my Curriculum Vitae" was blocked,
    with no override and no exit, on the commonest statement a page has.

    The cost of the narrowing is stated plainly: a bare "Jane Roe" in a
    statement is no longer a guarded name, so a letter naming her passes this
    gate. That is the right side to err on. The model is already instructed
    not to name anyone when the page forbids it (`letters._shape_instructions`);
    this gate is the backstop, and a backstop that blocks ordinary prose with
    no way past it fails the letter outright.
    """
    guarded = set()
    for phrase in capitalised_phrases(text):
        words = [word.casefold().rstrip(".") for word in phrase.split()]
        if words[0] in _PERSON_TITLES or any(word in _GROUP_WORDS for word in words):
            guarded.add(phrase)
    return guarded


def check_naming_forbidden(
    content: LetterContent,
    *,
    naming: str,
    institution_names: frozenset[str],
    research_names: frozenset[str],
) -> tuple[LetterGateViolation, ...]:
    """No named person, group or lab of the target institution, when forbidden.

    Every guarded name is matched as TEXT, on word boundaries, against the
    letter with its whitespace flattened. Matching whole proper-noun phrases
    instead could not see "Technical University of Munich" (the dominant shape
    of a real institution name), nor a single-word one, nor a name inside a
    longer run -- "Dear Professor Jane Roe," is one phrase and not equal to
    the name it carries (Task 9 review). Flattening is what lets a name
    survive the line break model prose puts in the middle of it.

    What may BE a guarded name is where the narrowing lives instead: catalog
    institution rows, and only the person-or-body phrases
    (`names_worth_guarding`) read off the programme's own page.

    `header_block` is scanned with the units: it is letter content, it is
    where a salutation lands, and "Dear Professor Jane Roe," is the first
    place a real "do not name" rule looks.

    Pre-flight ruling 3b: the spec says "RESEARCH rows" and `ProgramStatement`
    has no such kind (COMPETENCY, DOCUMENT, FORMAT, LANGUAGE, OTHER), so the
    caller scans them all -- a named group or lab appears in whichever kind the
    reader happened to label.

    A hit blocks and there is no override, because there is nobody to
    override: the page said do not name, and nobody reviews this letter.
    """
    if naming != "FORBIDDEN":
        return ()
    patterns = [
        re.compile(rf"\b{re.escape(_flat(name))}\b", re.IGNORECASE)
        for name in institution_names | research_names
        if name.strip()
    ]
    violations: list[LetterGateViolation] = []
    for archetype, text in [("HEADER_BLOCK", content.header_block or "")] + [
        (unit.archetype, unit.text) for unit in content.units
    ]:
        named = {match.group() for pattern in patterns for match in pattern.finditer(_flat(text))}
        violations.extend(
            LetterGateViolation(
                GateCode.NAMING_FORBIDDEN,
                f"the page forbids naming; the letter names {phrase!r}",
                archetype,
            )
            for phrase in sorted(named)
        )
    return tuple(violations)


def _flat(text: str) -> str:
    """One space between words, so a name survives a line break."""
    return " ".join(text.split())


def check_prompt_requirement_unmet(
    content: LetterContent, *, questions: list[dict[str, object]]
) -> tuple[LetterGateViolation, ...]:
    answered = {unit.answers_question for unit in content.units if unit.answers_question}
    return tuple(
        LetterGateViolation(GateCode.PROMPT_REQUIREMENT_UNMET, f"unanswered: {q['id']}", None)
        for q in questions
        if q["id"] not in answered
    )


_WHITESPACE = re.compile(r"\s+")
_HANGUL = re.compile(r"[가-힣]")
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[一-鿿]")
_NON_LATIN_SCRIPTS = {"ko": _HANGUL, "ja": _KANA, "zh": _HAN}


def script_of(document_language: str) -> re.Pattern[str] | None:
    """The script a language is written in, or None for a Latin-script one.

    The PRIMARY SUBTAG only: `document_language` holds up to ten characters,
    so "ja-JP" and "zh-Hans" are storable. `letter_shape.counts_characters`
    became subtag-aware in one round and this check did not, which widened the
    gap it was closing -- those were exactly the values newly exempted from
    every word bound, leaving the check that the letter is in that script off
    as well. One function now, read by both.
    """
    return _NON_LATIN_SCRIPTS.get(document_language.lower().split("-")[0])


def _normalised_sentences(content: LetterContent) -> set[str]:
    sentences: set[str] = set()
    for unit in content.units:
        for sentence in _SENTENCE_SPLIT.split(unit.text):
            normalised = _WHITESPACE.sub(" ", sentence.strip().lower())
            if normalised:
                sentences.add(normalised)
    return sentences


def check_duplicates_paired_document(
    content_a: LetterContent, content_b: LetterContent, *, threshold: float = 0.5
) -> tuple[LetterGateViolation, ...]:
    set_a, set_b = _normalised_sentences(content_a), _normalised_sentences(content_b)
    if not set_a or not set_b:
        return ()
    overlap = len(set_a & set_b) / len(set_a | set_b)
    if overlap > threshold:
        return (
            LetterGateViolation(
                GateCode.DUPLICATES_PAIRED_DOCUMENT, f"{overlap:.0%} sentence overlap", None
            ),
        )
    return ()


def check_header_block_missing(
    content: LetterContent, *, required: bool
) -> tuple[LetterGateViolation, ...]:
    if required and not content.header_block:
        return (LetterGateViolation(GateCode.HEADER_BLOCK_MISSING, "no header_block set", None),)
    return ()


def check_language_mismatch(
    content: LetterContent, *, document_language: str
) -> tuple[LetterGateViolation, ...]:
    if content.language.lower() != document_language.lower():
        return (
            LetterGateViolation(
                GateCode.LANGUAGE_MISMATCH,
                f"declared {content.language!r}, expected {document_language!r}",
                None,
            ),
        )
    script = script_of(document_language)
    if script is None:
        return ()
    all_text = "".join(unit.text for unit in content.units)
    non_space = [ch for ch in all_text if not ch.isspace()]
    if not non_space:
        return ()
    matched = sum(1 for ch in non_space if script.match(ch))
    if matched / len(non_space) < 0.5:
        return (LetterGateViolation(GateCode.LANGUAGE_MISMATCH, "script ratio below 50%", None),)
    return ()


_EXEMPT_ARCHETYPES = {"OPENING", "CLOSING"}
# 2026-09-14 (N-15): a fit paragraph must rest on a programme fact, not only
# on the student's own -- a WHY_PROGRAMME unit that survives a find-and-
# replace of the university's name is saying nothing about this programme.
_SOURCED_REQUIRED_ARCHETYPES = {"WHY_PROGRAMME"}


def check_generic_paragraph(content: LetterContent) -> tuple[LetterGateViolation, ...]:
    violations: list[LetterGateViolation] = []
    for unit in content.units:
        if unit.archetype in _EXEMPT_ARCHETYPES:
            continue
        kinds = {claim.kind.value for claim in unit.claims}
        if not kinds & {"FACTUAL", "SOURCED"}:
            violations.append(
                LetterGateViolation(
                    GateCode.GENERIC_PARAGRAPH, "no FACTUAL or SOURCED claim", unit.archetype
                )
            )
        elif unit.archetype in _SOURCED_REQUIRED_ARCHETYPES and "SOURCED" not in kinds:
            violations.append(
                LetterGateViolation(
                    GateCode.GENERIC_PARAGRAPH,
                    f"{unit.archetype} without SOURCED claim",
                    unit.archetype,
                )
            )
    return tuple(violations)


# --- 2026-09-14 amendment (docs/research/2026-09-14-letter-storytelling-evidence.md §3) ---


def _unit_sentences(unit: LetterUnit) -> set[str]:
    return {
        _WHITESPACE.sub(" ", s.strip().lower())
        for s in _SENTENCE_SPLIT.split(unit.text)
        if s.strip()
    }


def check_duplicates_sibling_answers(
    content: LetterContent, *, threshold: float = 0.5
) -> tuple[LetterGateViolation, ...]:
    answers = [u for u in content.units if u.answers_question]
    violations: list[LetterGateViolation] = []
    for i, a in enumerate(answers):
        for b in answers[i + 1 :]:
            set_a, set_b = _unit_sentences(a), _unit_sentences(b)
            if not set_a or not set_b:
                continue
            overlap = len(set_a & set_b) / len(set_a | set_b)
            if overlap > threshold:
                violations.append(
                    LetterGateViolation(
                        GateCode.DUPLICATES_SIBLING_ANSWER,
                        f"{a.answers_question} and {b.answers_question}: "
                        f"{overlap:.0%} sentence overlap",
                        a.archetype,
                    )
                )
    return tuple(violations)


_PLURAL = re.compile(r"\b(we|our|us|ours)\b", re.IGNORECASE)
_SINGULAR = re.compile(r"\b(i|my|me|mine)\b", re.IGNORECASE)
_EXAMPLE_ARCHETYPES = {"LEADERSHIP_EXAMPLE", "RELATIONSHIP_COMMUNITY"}


def check_first_person_plural(content: LetterContent) -> tuple[LetterGateViolation, ...]:
    violations: list[LetterGateViolation] = []
    for unit in content.units:
        if unit.archetype not in _EXAMPLE_ARCHETYPES:
            continue
        plural, singular = len(_PLURAL.findall(unit.text)), len(_SINGULAR.findall(unit.text))
        if plural > singular:
            violations.append(
                LetterGateViolation(
                    GateCode.FIRST_PERSON_PLURAL,
                    f"{plural} plural vs {singular} singular first-person words",
                    unit.archetype,
                )
            )
    return tuple(violations)


def check_storyline_drift(
    content: LetterContent, *, storyline: Storyline | None
) -> tuple[LetterGateViolation, ...]:
    if storyline is None:
        return ()
    used = {
        claim.fact_id
        for unit in content.units
        for claim in unit.claims
        if claim.fact_id is not None
    }
    missing = [a for a in storyline.anchors if a not in used]
    needed = min(2, len(storyline.anchors))
    if len(storyline.anchors) - len(missing) < needed:
        return (
            LetterGateViolation(
                GateCode.STORYLINE_DRIFT,
                f"anchors not used: {', '.join(map(str, missing))}",
                None,
            ),
        )
    return ()


def run_letter_gates(
    content: LetterContent,
    *,
    forbidden_names: frozenset[str],
    questions: list[dict[str, object]],
    header_block_required: bool,
    document_language: str,
    paired_content: LetterContent | None = None,
    storyline: Storyline | None = None,
    naming: str = "UNSTATED",
    institution_names: frozenset[str] = frozenset(),
    research_names: frozenset[str] = frozenset(),
) -> tuple[LetterGateViolation, ...]:
    """Runs every deterministic gate and concatenates their violations. Does
    NOT fold in claim-verdict blocking (UNSUPPORTED / immigration-UNCERTAIN)
    -- that comes from verify_letter_claims separately, because a
    LetterClaimVerdict and a LetterGateViolation are different shapes for a
    reason: verdicts are per-claim and drive the fact-overlay UI, gate
    violations are per-check and drive the retry loop. Task 12's generation
    service combines both tuples to decide whether to retry."""
    violations: list[LetterGateViolation] = []
    for unit in content.units:
        violations.extend(check_claim_coverage(unit))
    violations.extend(check_wrong_institution(content, forbidden_names=forbidden_names))
    violations.extend(check_prompt_requirement_unmet(content, questions=questions))
    violations.extend(check_header_block_missing(content, required=header_block_required))
    violations.extend(check_language_mismatch(content, document_language=document_language))
    violations.extend(check_generic_paragraph(content))
    violations.extend(check_duplicates_sibling_answers(content))
    violations.extend(check_first_person_plural(content))
    violations.extend(check_storyline_drift(content, storyline=storyline))
    violations.extend(
        check_naming_forbidden(
            content,
            naming=naming,
            institution_names=institution_names,
            research_names=research_names,
        )
    )
    if paired_content is not None:
        violations.extend(check_duplicates_paired_document(content, paired_content))
    return tuple(violations)
