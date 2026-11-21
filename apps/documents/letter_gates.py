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
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
from uuid import UUID

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
    #: One unit per requested archetype, and none unrequested. Measured live
    #: 2026-09-25: six archetypes came back as 21 one-claim units.
    UNIT_STRUCTURE = "UNIT_STRUCTURE"
    #: A sentence about what the programme offers, with no SOURCED claim.
    UNSOURCED_PROGRAMME_CLAIM = "UNSOURCED_PROGRAMME_CLAIM"
    #: Stock AI vocabulary, participial -ing trailers, em-dashes, or flat
    #: sentence-length uniformity that _INSTRUCTIONS forbids (human-voice.md).
    AI_STYLE = "AI_STYLE"


@dataclass(frozen=True)
class LetterGateViolation:
    code: GateCode
    detail: str
    unit_archetype: str | None = None
    #: False for a warning: carried on the result for the student to see, never
    #: a reason to block, retry or hold the letter (spec 2026-10-14 §5, §4.6).
    blocking: bool = True
    #: Closed-vocabulary subcode safe to include in retry instructions without
    #: leaking model-authored prose into developer prompts.
    subcode: str | None = None


SAFE_GATE_SUBCODES: frozenset[str] = frozenset(
    {
        "stock_phrase",
        "participial_trailer",
        "em_dash",
        "closing_summary",
        "nominalization_density",
        "uniform_sentence_length",
        "consecutive_similar_length",
        "cohort_overlap",
        "declared_voice_missing",
    }
)


#: Where a sentence ends, for every script a letter is written in. Latin, Arabic
#: (؟) and Armenian (։) terminals end a sentence only before whitespace, so a
#: version number ("3.11") never splits; CJK full-width terminals take no space
#: after them and split before the next visible character, so a final one leaves
#: no empty trailing sentence. ponytail: Greek writes its question mark as ";"
#: (U+037E normalises to it), indistinguishable from a semicolon without the
#: letter's language, so Greek questions are not split; pass the language in
#: if a Greek letter ever needs it.
#: Invisible marks (zero-width space and joiners, left-to-right and right-to-left
#: marks, word joiner, BOM) count as part of the gap after a terminal: hygiene
#: strips them, so a split that depended on them would change the sentence
#: count across hygiene and fail `hygienic_letter_content` (final review, an
#: Arabic "؟" followed by U+200F). At least one real space is still required.
_INVISIBLE = "\u200b-\u200f\u2060\ufeff"
_SENTENCE_SPLIT = re.compile(
    rf"(?<=[.!?؟։])[{_INVISIBLE}]*\s[\s{_INVISIBLE}]*|(?<=[。！？])[\s{_INVISIBLE}]*(?=\S)"
)
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
            run, pending = _close(run, phrases, minimum_words), []
            continue
        if part[:1].isupper():
            run.extend(pending)
            pending = []
            run.append(part)
        elif run and part.casefold() in _CONNECTORS:
            pending.append(part)
        else:
            run, pending = _close(run, phrases, minimum_words), []
    _close(run, phrases, minimum_words)
    return phrases


def _close(run: list[str], phrases: list[str], minimum_words: int) -> list[str]:
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
    """Split ``text`` into sentences with their ``[start, end)`` offsets, for every
    letter script (see ``_SENTENCE_SPLIT``).

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
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
_ARMENIAN = re.compile(r"[԰-֏]")
_GEORGIAN = re.compile(r"[Ⴀ-ჿ]")
#: Languages written in one non-Latin script. Serbian (Cyrillic and Latin) and
#: Kazakh (Cyrillic, moving to Latin) are deliberately absent: a correct letter
#: in either script must not fail the check.
_NON_LATIN_SCRIPTS = {
    "ko": _HANGUL, "ja": _KANA, "zh": _HAN,
    "ru": _CYRILLIC, "uk": _CYRILLIC, "be": _CYRILLIC, "bg": _CYRILLIC, "mk": _CYRILLIC,
    "el": _GREEK, "ar": _ARABIC, "hy": _ARMENIAN, "ka": _GEORGIAN,
}
#: Languages whose length is counted in characters, not words. A separate set
#: from the script table on purpose: `letter_shape.counts_characters` used to
#: read `script_of`, so every script added here would have switched that
#: language's word caps off.
CHARACTER_COUNTED_LANGUAGES = frozenset({"ko", "ja", "zh"})


def script_of(document_language: str) -> re.Pattern[str] | None:
    """The script a language is written in, or None for a Latin-script one.

    The PRIMARY SUBTAG only: `document_language` holds up to ten characters,
    so "ja-JP" and "zh-Hans" are storable.
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


def check_generic_paragraph(
    content: LetterContent,
    *,
    programme_input_ids: frozenset[UUID] = frozenset(),
    has_facts: bool = True,
) -> tuple[LetterGateViolation, ...]:
    """Every body paragraph rests on a fact; WHY_PROGRAMME rests on a verified
    programme fact. Only a SOURCED claim citing one of `programme_input_ids`
    (research rows verified for THIS programme) satisfies WHY_PROGRAMME: a
    SOURCED claim carrying only a URL was a link the model could make up. When
    nothing is verified for the programme, or the student has no confirmed
    facts, the miss is a warning -- blocking it would block every such letter."""
    violations: list[LetterGateViolation] = []
    has_programme_sourced_unit = bool(programme_input_ids) and any(
        u.archetype in _SOURCED_REQUIRED_ARCHETYPES
        and any(
            c.kind == ClaimKind.SOURCED and c.input_id in programme_input_ids
            for c in u.claims
        )
        for u in content.units
    )
    for unit in content.units:
        if unit.archetype in _EXEMPT_ARCHETYPES:
            continue
        kinds = {claim.kind.value for claim in unit.claims}
        if not kinds & {"FACTUAL", "SOURCED"}:
            violations.append(
                LetterGateViolation(
                    GateCode.GENERIC_PARAGRAPH,
                    "no FACTUAL or SOURCED claim"
                    if has_facts
                    else "no confirmed facts: written from the programme and the plan only",
                    unit.archetype,
                    blocking=has_facts,
                )
            )
        elif (
            unit.archetype in _SOURCED_REQUIRED_ARCHETYPES
            and not has_programme_sourced_unit
            and not any(
                claim.kind == ClaimKind.SOURCED and claim.input_id in programme_input_ids
                for claim in unit.claims
            )
        ):
            violations.append(
                LetterGateViolation(
                    GateCode.GENERIC_PARAGRAPH,
                    f"{unit.archetype} without a SOURCED claim citing a verified programme fact"
                    if programme_input_ids
                    else f"{unit.archetype} not specific to this programme: "
                    "no verified programme fact",
                    unit.archetype,
                    blocking=bool(programme_input_ids),
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
    for a, b in combinations(answers, 2):
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


def check_unit_structure(
    content: LetterContent, *, archetypes: tuple[str, ...]
) -> tuple[LetterGateViolation, ...]:
    """A unit is a paragraph, not a claim. An empty `archetypes` skips the
    check: a short-answer set is keyed by question instead."""
    if not archetypes:
        return ()
    violations: list[LetterGateViolation] = []
    seen: set[str] = set()
    for unit in content.units:
        if unit.archetype not in archetypes:
            detail = "archetype was not requested"
        elif unit.archetype in seen:
            detail = "archetype split across several units"
        else:
            seen.add(unit.archetype)
            continue
        if not any(v.unit_archetype == unit.archetype for v in violations):
            violations.append(
                LetterGateViolation(GateCode.UNIT_STRUCTURE, detail, unit.archetype)
            )
    return tuple(violations)


#: Words that describe what a programme offers. A sentence using one asserts a
#: fact about the programme, and only a page we read can vouch for that -- a
#: FACTUAL or DECLARED claim is about the applicant. Lowercase on purpose:
#: `_has_trigger` already catches a capitalised name, and what it missed
#: (measured live 2026-09-25) was "the programme's module focused on
#: free-energy methods", invented from the student's wish to learn them.
# ponytail: English words only; another language relies on the prompt rule.
# Widen per language when a letter in it shows the same invention.
_PROGRAMME_OFFERING = re.compile(
    # Not lab/laboratory: measured live 2026-09-25, "what is tested in the
    # laboratory" is a place, not an offering, and a named lab is capitalised.
    r"\b("
    r"modules?|electives?|curricul(?:um|a)|speciali[sz]ations?|research groups?|"
    r"professors?|supervisors?|facult(?:y|ies)|"
    r"wahlpflicht(?:modul\w*|fach\w*|fächer\w*)?|lehrst(?:uhl\w*|ühl\w*)|"
    r"forschungsgruppen?|professor(?:en|innen)|"
    r"enseignements?|équipe[s]?\s+de\s+recherche|professeurs?|"
    r"seçmeli\s+ders\w*|müfredat\w*|araştırma\s+gru(?:bu|pları)\w*|anabilim\s+dalı\w*|"
    r"модул(?:ь|и|ей|ях)|специализаци(?:я|и|ей)|исследовательск\w+\s+групп\w+|"
    r"профессор(?:а|ов)?|научн\w+\s+руководител\w+"
    r")\b",
    re.IGNORECASE,
)
#: The applicant's own past: a supervisor or lab there is theirs, not the
#: programme's.
_APPLICANT_PAST_ARCHETYPES = {
    "ACADEMIC_PREPARATION", "PERSONAL_BACKGROUND", "LEADERSHIP_EXAMPLE", "RELATIONSHIP_COMMUNITY",
}
#: The applicant's future at home: a faculty, supervisors or a research group
#: there are where they will work, not what this programme offers.
_APPLICANT_FUTURE_ARCHETYPES = {"CAREER_PLAN_RETURN", "HOME_COUNTRY_CONTRIBUTION"}


def check_unsourced_programme_claim(
    content: LetterContent, *, programme_input_ids: frozenset[UUID] = frozenset()
) -> tuple[LetterGateViolation, ...]:
    """A sentence about what the programme offers needs a SOURCED claim citing a
    research row verified for this programme (`programme_input_ids`). A SOURCED
    claim carrying only a URL does not count: that was a link the model could
    make up (spec 2026-10-14 §5), the same rule `check_generic_paragraph` applies.

    With nothing verified for the programme the miss is a warning, as spec §5
    has it: the offering words also appear in the student's own needs ("I am
    looking for supervisors who work on catalysis"), and blocking those would
    block every such letter while research fit is off (final review). The
    student's own past and their future at home are never programme claims."""
    violations: list[LetterGateViolation] = []
    for unit in content.units:
        if unit.archetype in _APPLICANT_PAST_ARCHETYPES | _APPLICANT_FUTURE_ARCHETYPES:
            continue
        for sentence, start, end in sentence_spans(unit.text):
            if not _PROGRAMME_OFFERING.search(sentence):
                continue
            # Overlap, not enclosure: hygienic_letter_content widens a span
            # onto its sentence before generation runs any gate.
            if not any(
                claim.kind == ClaimKind.SOURCED
                and claim.input_id in programme_input_ids
                and claim.span_start < end
                and claim.span_end > start
                for claim in unit.claims
            ):
                violations.append(
                    LetterGateViolation(
                        GateCode.UNSOURCED_PROGRAMME_CLAIM,
                        sentence.strip(),
                        unit.archetype,
                        blocking=bool(programme_input_ids),
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


_AI_STOCK_RE = re.compile(
    r"\b(?:"
    r"delv(?:e|es|ed|ing)|tapestry|testament\s+to|pivotal\s+moment|"
    r"underscor(?:e|es|ed|ing)\s+(?:its|the|my|a|an|how)|evolving\s+landscape|"
    r"breathtaking|nestled|boasts|(?:serves|stands)\s+as\s+a\s+testament|"
    r"marks\s+a\s+pivotal|i\s+have\s+always\s+wanted\s+to\s+be|"
    r"not\s+only\s+[^.!?]{1,60}\s+but\s+also|"
    r"it\s+is\s+not\s+(?:just|merely)\s+[^.!?]{1,50},\s*it\s+is|"
    r"meticulous(?:ly)?|bolster(?:ed|s|ing)?|deep\s+dive|unwavering(?:ly)?|"
    r"wholeheartedly|foster(?:ed|s|ing)?\s+(?:a|an|the|my)|"
    r"intricate\s+(?:web|tapestry|balance|interplay)|"
    r"vibrant\s+(?:community|ecosystem|environment|academic)|camaraderie|palpable|"
    r"unterstreicht\s+die\s+bedeutung|von\s+entscheidender\s+bedeutung|"
    r"hiermit\s+bewerbe\s+ich\s+mich|seit\s+meiner\s+kindheit|"
    r"zusammenfassend\s+l[äa]sst\s+sich\s+sagen|"
    r"souligne\s+l['\u2019]importance|il\s+convient\s+de\s+souligner|"
    r"depuis\s+mon\s+enfance|c['\u2019]est\s+avec\s+un\s+vif\s+int[ée]r[êe]t|"
    r"je\s+suis\s+fermement\s+persuad[ée]|"
    r"подчеркивает\s+важность|играет\s+ключевую\s+роль|с\s+самого\s+детства|"
    r"в\s+заключение\s+следует\s+отметить|"
    r"önemini\s+vurgulamaktadır|kritik\s+bir\s+rol\s+oynamaktadır|"
    r"çocukluğumdan\s+beri|sonuç\s+olarak\s+belirtmek\s+gerekirse"
    r")\b",
    re.IGNORECASE,
)
_AI_PARTICIPIAL_TRAILER_RE = re.compile(
    r",\s+(?:highlighting|reflecting|showcasing|underscoring)\s+(?:the|my|its|how|a)\b",
    re.IGNORECASE,
)
_AI_CLOSING_SUMMARY_RE = re.compile(
    r"^\s*(?:overall|ultimately|in\s+summary|in\s+conclusion|all\s+in\s+all),\s+"
    r"(?:this\s+(?:experience|project|role|work)|i\s+learned|it\s+taught\s+me)\b",
    re.IGNORECASE,
)
_NOMINALIZATION_WORD_RE = re.compile(
    r"\b(?:"
    r"[a-zàâäéèêëîïôöùûüç]{4,}(?:tions?|ments?|ness(?:es)?|it(?:y|ies|és?)|ances?|ences?)|"
    r"[a-zäöüß]{4,}(?:ungen|ung|keiten|keit|heiten|heit|itäten|ität)|"
    r"[а-яё]{4,}(?:ост(?:ь|и|ей|ью)|ени(?:е|я|й|ю|ем)|ани(?:е|я|й|ю|ем))|"
    r"[a-zçğıöşü]{4,}(?:l[ıiuü]k(?:lar|ler)?|m[ae]s[ıi])"
    r")\b",
    re.IGNORECASE,
)
_CONTENT_WORD_RE = re.compile(r"[^\W\d_]{4,}")
_VOICE_STOPWORDS = frozenset(
    {
        "that", "this", "with", "from", "have", "were", "been", "their", "there", "which",
        "would", "could", "should", "about", "after", "before", "during", "while", "where",
        "when", "into", "through", "between", "under", "over", "also", "more", "most", "some",
        "such", "only", "other", "than", "then", "them", "they", "these", "those", "your",
        "want", "will", "work", "study", "programme", "program", "master", "masters",
        "university", "research", "project", "course",
    }
)


def _has_three_consecutive_uniform_sentences(counts: list[int]) -> bool:
    """True when 3+ consecutive sentences of >=12 words differ by <=1 word."""
    return any(
        min(w) >= 12 and (max(w) - min(w)) <= 1 for w in zip(counts, counts[1:], counts[2:])
    )


def check_ai_style(content: LetterContent) -> tuple[LetterGateViolation, ...]:
    """Deterministic enforcement of the anti-AI style and burstiness rules in
    `letters._INSTRUCTIONS` (`docs/research/2026-09-28-letter-engine/human-voice.md`)."""
    violations: list[LetterGateViolation] = []
    for unit in content.units:
        text = unit.text
        stock_match = _AI_STOCK_RE.search(text)
        if stock_match is not None:
            violations.append(
                LetterGateViolation(
                    GateCode.AI_STYLE,
                    f"banned AI phrase: {stock_match.group(0)}",
                    unit.archetype,
                    subcode="stock_phrase",
                )
            )
            continue
        trailer_match = _AI_PARTICIPIAL_TRAILER_RE.search(text)
        if trailer_match is not None:
            violations.append(
                LetterGateViolation(
                    GateCode.AI_STYLE,
                    f"participial trailer: {trailer_match.group(0)}",
                    unit.archetype,
                    subcode="participial_trailer",
                )
            )
            continue
        if "\u2014" in text:
            violations.append(
                LetterGateViolation(
                    GateCode.AI_STYLE,
                    "em dash used",
                    unit.archetype,
                    subcode="em_dash",
                )
            )
            continue
        spans = sentence_spans(text)
        if len(spans) >= 2:
            last_sentence = spans[-1][0]
            if _AI_CLOSING_SUMMARY_RE.search(last_sentence) is not None:
                violations.append(
                    LetterGateViolation(
                        GateCode.AI_STYLE,
                        "moralizing paragraph-closing summary",
                        unit.archetype,
                        subcode="closing_summary",
                    )
                )
                continue
        nom_violation = False
        for sent_text, _, _ in spans:
            words = sent_text.split()
            if 0 < len(words) <= 28:
                noms = {m.lower() for m in _NOMINALIZATION_WORD_RE.findall(sent_text)}
                if len(noms) >= 5:
                    violations.append(
                        LetterGateViolation(
                            GateCode.AI_STYLE,
                            "noun-heavy nominalization density",
                            unit.archetype,
                            subcode="nominalization_density",
                        )
                    )
                    nom_violation = True
                    break
        if nom_violation:
            continue
        counts = [len(s.split()) for s, _, _ in spans if s.strip()]
        if len(counts) >= 4 and min(counts) >= 10 and (max(counts) - min(counts)) <= 2:
            violations.append(
                LetterGateViolation(
                    GateCode.AI_STYLE,
                    "uniform sentence lengths across paragraph",
                    unit.archetype,
                    subcode="uniform_sentence_length",
                )
            )
        elif len(counts) >= 3 and _has_three_consecutive_uniform_sentences(counts):
            violations.append(
                LetterGateViolation(
                    GateCode.AI_STYLE,
                    "three consecutive sentences of near-identical length",
                    unit.archetype,
                    subcode="consecutive_similar_length",
                )
            )
    return tuple(violations)


def _salient_words(text: str) -> set[str]:
    return {
        w.casefold()
        for w in _CONTENT_WORD_RE.findall(text)
        if w.casefold() not in _VOICE_STOPWORDS
    }


def check_declared_voice_retention(
    content: LetterContent,
    *,
    declared_input_texts: Mapping[UUID, str] = {},
) -> tuple[LetterGateViolation, ...]:
    """Advisory check (`human-voice.md` §5, Implication #4): when a unit cites a
    student-authored `DECLARED` input containing >=5 salient content words, at
    least one salient content word from the student's input should survive in
    the unit rather than being completely paraphrased away."""
    if not declared_input_texts:
        return ()
    violations: list[LetterGateViolation] = []
    for unit in content.units:
        unit_words = _salient_words(unit.text)
        for claim in unit.claims:
            if (
                claim.kind != ClaimKind.DECLARED
                or claim.input_id is None
                or claim.input_id not in declared_input_texts
            ):
                continue
            source_words = _salient_words(declared_input_texts[claim.input_id])
            if len(source_words) >= 5 and not (unit_words & source_words):
                violations.append(
                    LetterGateViolation(
                        GateCode.AI_STYLE,
                        "declared claim preserves none of the student's own terms",
                        unit.archetype,
                        blocking=False,
                        subcode="declared_voice_missing",
                    )
                )
                break
    return tuple(violations)


def check_cohort_overlap(
    content: LetterContent,
    *,
    cohort_sentences: frozenset[str] = frozenset(),
    threshold: float = 0.35,
) -> tuple[LetterGateViolation, ...]:
    """Cross-student sameness gate (`human-voice.md` §2 TUM court ruling &
    `2026-10-12` Implication #5): flags a paragraph whose sentences overlap
    with recent letters written for other students targeting the same programme."""
    if not cohort_sentences:
        return ()
    violations: list[LetterGateViolation] = []
    for unit in content.units:
        unit_sents = _unit_sentences(unit)
        if not unit_sents:
            continue
        overlap = len(unit_sents & cohort_sentences) / len(unit_sents)
        if overlap > threshold:
            violations.append(
                LetterGateViolation(
                    GateCode.GENERIC_PARAGRAPH,
                    f"cohort sentence overlap: {overlap:.0%}",
                    unit.archetype,
                    subcode="cohort_overlap",
                )
            )
    return tuple(violations)


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
    programme_input_ids: frozenset[UUID] = frozenset(),
    has_facts: bool = True,
    archetypes: tuple[str, ...] = (),
    declared_input_texts: Mapping[UUID, str] = {},
    cohort_sentences: frozenset[str] = frozenset(),
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
    violations.extend(
        check_generic_paragraph(
            content, programme_input_ids=programme_input_ids, has_facts=has_facts
        )
    )
    violations.extend(check_duplicates_sibling_answers(content))
    violations.extend(check_first_person_plural(content))
    violations.extend(check_storyline_drift(content, storyline=storyline))
    violations.extend(check_unit_structure(content, archetypes=archetypes))
    violations.extend(check_ai_style(content))
    violations.extend(
        check_declared_voice_retention(content, declared_input_texts=declared_input_texts)
    )
    violations.extend(check_cohort_overlap(content, cohort_sentences=cohort_sentences))
    violations.extend(
        check_unsourced_programme_claim(content, programme_input_ids=programme_input_ids)
    )
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
