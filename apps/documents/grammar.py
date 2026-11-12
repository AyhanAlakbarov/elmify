"""The rule grammar: four slots, closed lists, one free topic.

Design: docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md §6,
amended by 2026-09-26-requirement-reader-addendum-design.md §6.

A requirement sentence is never read as a sentence. It is taken apart into
`document`, `operation`, `value` and `scope`, each a closed question with a
probability, and a rule exists only when every slot fills at its bar.

**Every operation projects onto a sink that already exists** -- a constraint key
the renderer checks, a directive the generator reads, a LetterShape field the
letter engine uses. An operation whose value names no sink is `unapplied`: kept
verbatim, shown on the document, counted (§6.5), and never improvised into the
writing prompt. That is the one door this design keeps shut.

Nothing here calls a model. `grammar_questions` and `grammar_values` ask; this
module defines what may be asked and where each answer goes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, get_args

from .constraints import (
    _INCLUDE_TARGETS,
    _ORDER_DIRECTIONS,
    _ORDER_TARGETS,
    _SECTIONS,
    CAP_SECTIONS,
)

Document = Literal["cv", "motivation_letter", "reference_letter", "other"]
Operation = Literal[
    "limit", "language", "format", "include", "order", "emphasise", "style",
    "topic", "student_action", "form", "naming", "coverage", "other",
]

DOCUMENTS: tuple[str, ...] = get_args(Document)
OPERATIONS: tuple[str, ...] = get_args(Operation)

#: A rule's operation: a slot's, or `referee`, which no slot is classified as.
#: Every sentence about a reference letter is asked the referee questions on
#: top of its own operation, so the sentence keeps its sink (a student action)
#: and also yields one `referee` rule per fact it states.
RuleOperation = Operation | Literal["referee", "file"]

#: What a page can state about its reference letters, field -> closed values.
#: Owner-approved 2026-10-08 with the student-dashboard session, whose
#: application-route catalogue reads `Program.referee_requirements`. NOT_STATED
#: never becomes a rule, so a field with no record was not stated; NONE_REQUIRED
#: is a page saying no letters are needed, which is a different fact.
REFEREE_FIELDS: dict[str, tuple[str, ...]] = {
    "count": ("ONE", "TWO", "THREE_OR_MORE", "NONE_REQUIRED", "NOT_STATED"),
    "kind": ("ACADEMIC", "PROFESSIONAL", "EITHER", "NOT_STATED"),
    "mode": ("UPLOAD_GENERIC", "UPLOAD_ADDRESSED", "PORTAL_INVITE", "REFEREE_SENDS",
             "NOT_STATED"),
    "institutional_email_required": ("YES", "NO", "NOT_STATED"),
    "due": ("WITH_APPLICATION", "BEFORE_DEADLINE", "NOT_STATED"),
}

#: What a page can state about the FILE a document is submitted as.
#: NOT_STATED never becomes a rule. `document` EVERY_DOCUMENT is a rule for all
#: the applicant's documents at once ("all documents as one PDF, max 10 MB").
FILE_FIELDS: dict[str, tuple[str, ...]] = {
    "document": ("CV", "MOTIVATION_LETTER", "REFERENCE_LETTER", "TRANSCRIPT", "DIPLOMA",
                 "PASSPORT", "LANGUAGE_CERTIFICATE", "EVERY_DOCUMENT", "NOT_STATED"),
    "format": ("PDF", "JPG", "PDF_OR_JPG", "NOT_STATED"),
    "combine": ("ONE_FILE", "SEPARATE_FILES", "NOT_STATED"),
}

#: A file thing a sentence can name. Matched on the raw line; code decides only
#: WHETHER to ask, never what the answer is. Lives here (not in grammar_values)
#: because derive.py imports it and grammar_values imports derive. ponytail:
#: English, German, French, Russian and Turkish words for file/size; a page in
#: another language still reaches the questions through "PDF"/"MB".
_FILE_TERMS = re.compile(
    r"\b(?:pdf|jpe?g|\d+(?:[.,]\d+)?\s*(?:mb|kb|mo|ko|megabytes?|kilobytes?)|file ?name"
    r"|one file|single file|datei|fichier|dosya|файл|мб|кб)\b"
    r"|\b[\w-]+\.(?:pdf|jpe?g|png)\b",
    re.IGNORECASE,
)

#: The units a length may be stated in. `pages` is a CV and letter unit;
#: `words` and `characters` are the letter's (ApplicationPrompt.letter_max_words,
#: letter_max_chars) and the CV's max_words / max_chars_incl_spaces.
#: `megabytes` is the file's size, the CV's max_bytes (render._check_max_bytes).
#: Added by §11 gate 7 (Task 11): R-048, R-060, R-067 and R-082 state a file cap
#: a page prints, the frontier judge derived max_bytes from it, and without
#: this unit the grammar could only call it `other`. The letter has no size
#: field, so a letter's megabytes cap is `unapplied`.
#: `entries` is a count of items in one CV section ("at most 3 publications"),
#: the CV's max_entries_per_section (spec 2026-10-12 §8, the planned
#: `cv_item_cap`); its section is asked per figure. The letter has none.
UNITS: tuple[str, ...] = ("pages", "words", "characters", "megabytes", "entries")

#: What one figure in a length sentence IS (addendum §6.1). `approximate` is
#: read as a cap, as decide_letter_shape has always read it: "about one page"
#: is never a floor, and a letter written to the approximation is inside it.
#: `section_limit` (one part of the document, "three parts of 400 words each")
#: and `another_statement` (a different statement in the same application) are
#: lengths, but of something the engine does not write as one document.
BOUNDS: tuple[str, ...] = (
    "maximum", "minimum", "approximate", "section_limit", "another_statement", "not_a_limit",
)

#: The bounds that set no cap or floor. Addendum §6.5: recorded, not yet
#: enforced -- the figure yields a `topic` rule carrying its sentence, which the
#: letter lands in `letter_written_requirements`, because the renderer has no
#: per-section check and a second statement is a document the engine does not
#: write (addendum §10). A TOLERANCE is not here and is not a bound at all:
#: "an exceedance of more than 10 percent" states no length of the document,
#: so the sentence's operation is `topic` and no figure of it is asked a bound.
NOTE_BOUNDS: frozenset[str] = frozenset({"section_limit", "another_statement"})

#: The letter's form (derive.LetterVerdict's `form` minus its "none"), onto
#: LetterShape.form. A value outside it has no sink and is `unapplied`.
FORM_VALUES: tuple[str, ...] = ("essay", "formal_letter", "portal_form")

#: Whether the letter must, may or must not name a prospective supervisor
#: (LetterVerdict's `naming` minus "none"), onto LetterShape.naming.
NAMING_VALUES: tuple[str, ...] = ("required", "invited", "forbidden")

#: The CV-format verdict, unchanged in values from the 2026-09-13 spec so the
#: 48-row eval sheet still scores it. `third_party` left the list: it is the
#: scope slot's job now and a sentence can be both third-party and a format rule.
FORMAT_VERDICTS: tuple[str, ...] = (
    "europass_required", "europass_preferred", "any", "other_template", "not_a_format_rule",
)

#: Style values, seeded from docs/research/cv-style-rules.csv and letter-rules.csv
#: by §11 gate 7 and frozen here. Each names a sink below; a style rule with no
#: sink would be a rule nothing checks.
STYLE_VALUES: tuple[str, ...] = (
    "photo_required", "photo_forbidden", "signature_required", "date_of_issue_required",
    "date_of_birth_forbidden", "font_size_minimum", "font_family", "line_spacing",
    "margins", "signed_declaration", "handwritten", "single_file_bundle",
    # Added by §11 gate 7 (Task 11): a page states both (R-010, R-011, R-020,
    # R-042 and S-047's ETH/TUM for gaps; R-017 for hyperlinks) and each has a
    # CV checker already -- render._check_no_unexplained_gaps and
    # _check_prohibited_content -- that no slot could reach.
    "no_gaps", "no_hyperlinks",
    # Spec 2026-10-12 §8: how much of the history a CV must hold, and from
    # when. `cv_start_last_years` reads its number through `style_number`.
    "cv_complete", "cv_relevant_only",
    "cv_start_upper_secondary", "cv_start_first_degree", "cv_start_last_years",
)

#: What a condition may be about, limited to what the student ledger can answer.
#: Anything else is `other` and becomes a note -- a condition we cannot evaluate
#: must never silently apply to everyone.
CONDITION_KINDS: tuple[str, ...] = (
    "nationality", "degree_level", "work_experience", "track", "other",
)

#: Spec §8, the coverage operation's closed answers. `none` is the escape a
#: Choice needs when the list does not fit; it has no sink and is `unapplied`.
COVERAGE_VALUES: tuple[str, ...] = (
    "complete", "relevant_only", "from_upper_secondary", "from_first_degree",
    "last_n_years", "section_cap", "none",
)
#: The largest count of entries or span of years a coverage rule may carry.
#: Above it the figure is a misread digit, not a rule, as _IMPLAUSIBLE_MAX.
_COVERAGE_MAX = 50


def _plausible_count(number: object) -> bool:
    return isinstance(number, int) and not isinstance(number, bool) and 1 <= number <= _COVERAGE_MAX


def coverage_key(value: object) -> str:
    """The constraint key a coverage value writes, or "" when nothing can carry it.

    The value is the (kind, section, number) triple grammar_values builds,
    the same shape `order` uses for its pair. A cap naming a section outside
    CAP_SECTIONS -- education, languages -- has no sink: a page cap never
    removes a degree (spec §8).
    """
    if not (isinstance(value, tuple | list) and len(value) == 3):
        return ""
    kind, section, number = value
    if kind in ("complete", "relevant_only"):
        return "cv_scope"
    if kind in ("from_upper_secondary", "from_first_degree"):
        return "cv_start"
    if kind == "last_n_years":
        return "cv_start" if _plausible_count(number) else ""
    if kind == "section_cap":
        return "cv_item_cap" if section in CAP_SECTIONS and _plausible_count(number) else ""
    return ""


def coverage_rule_value(value: object) -> object:
    """The stored ConstraintRule.value for a coverage triple coverage_key accepts."""
    assert isinstance(value, tuple | list)
    kind, section, number = value
    if kind in ("complete", "relevant_only"):
        return kind
    if kind == "from_upper_secondary":
        return {"start": "upper_secondary"}
    if kind == "from_first_degree":
        return {"start": "first_degree"}
    if kind == "last_n_years":
        return {"start": "last_n_years", "years": number}
    return {"section": section, "max": number}

# Moved verbatim from derive.py so the grammar keeps the guards and Task 10's
# cut of derive.py cannot take them.
#: The smallest cap any real programme states. Grounded in the 119-rule research
#: catalogue (docs/research/letter-shape-rules.csv), whose shortest published
#: limits are in the hundreds of words and thousands of characters -- nothing
#: near these floors. A cap below one of them is a misread digit, not a rule,
#: and acting on it blocks every letter for that programme with nobody to see
#: why. Rejecting it costs only the cap: the default target then applies.
#:
#: Applies to CAPS only, never floors: a floor is already bounded above by
#: the page's own text, and a too-small floor is harmless (it only asks for
#: a longer letter, exactly like a false floor from a fabricated number).
_IMPLAUSIBLE_CAP = {"words": 50, "chars": 200, "pages": 0.25, "megabytes": 0.1, "entries": 1}

#: The largest figure any real programme states. Above this it is a misread, not a
#: rule: no motivation letter runs to twenty pages, and a floor above these blocks
#: every letter for the programme. Unlike the lower band this applies to FLOORS as
#: well as caps -- a too-small floor is harmless, an absurd one blocks everything --
#: and it also keeps max_pages inside its DecimalField(4,1) column, where an
#: overflow would raise inside read_and_derive's transaction and roll back the whole
#: read, statements and snapshot included.
#: A megabytes figure above 100 is a misread too -- or a kilobyte figure read
#: as megabytes ("300 KB"), which is exactly the reading this band must drop.
_IMPLAUSIBLE_MAX = {
    "words": 20_000, "chars": 100_000, "pages": 20, "megabytes": 100, "entries": 50,
}

#: operation -> the CV constraint key it writes, for the operations whose value
#: does not pick the key itself.
#: `photo_required` has its own key (spec 2026-10-12 §8) and its own checker,
#: render._check_photo_required. It used to return "" (unapplied) because the
#: only photo key, photo_allowed, stores "required" and "allowed" alike as
#: True. Every key here lacking a pre-flight checker stays, by the fix-round-1
#: ruling: a loud "no pre-flight check" is acceptable.
_CV_STYLE_SINK: dict[str, str] = {
    "photo_required": "photo_required",
    "photo_forbidden": "photo_allowed",
    "signature_required": "signature_required",
    "date_of_issue_required": "date_of_issue_required",
    "date_of_birth_forbidden": "date_of_birth_allowed",
    "font_size_minimum": "font",
    "font_family": "font",
    "no_gaps": "no_unexplained_gaps",
    "no_hyperlinks": "prohibited_content",
    "cv_complete": "cv_scope",
    "cv_relevant_only": "cv_scope",
    "cv_start_upper_secondary": "cv_start",
    "cv_start_first_degree": "cv_start",
    "cv_start_last_years": "cv_start",
}
_CV_LIMIT_SINK: dict[str, str] = {
    "pages": "max_pages",
    "words": "max_words",
    "characters": "max_chars_incl_spaces",
    "megabytes": "max_bytes",
    "entries": "max_entries_per_section",
}
#: The letter's sinks are LetterShape field names; apply_derived_shape writes
#: them onto ApplicationPrompt.letter_*.
_LETTER_LIMIT_SINK: dict[str, str] = {
    "pages": "max_pages", "words": "max_words", "characters": "max_chars",
}
#: A letter floor per unit. No column holds a page floor and no checker
#: measures one, so a page floor is `unapplied`. The CV has no floor sink at all.
_LETTER_FLOOR_SINK: dict[str, str] = {"words": "min_words", "characters": "min_chars"}
#: `single_file_bundle` is deliberately absent (fix round 1, finding 2,
#: controller ruling): `apps/funding/requirements.py` acts on nothing keyed by
#: `file_bundle`, so the mapping named a sink no checker reads. It returns ""
#: (unapplied) instead -- by the fix-round-1 ruling (finding 2).
_LETTER_STYLE_SINK: dict[str, str] = {
    "signed_declaration": "signed_declaration",
    "handwritten": "handwritten",
    "font_family": "font_family",
    "font_size_minimum": "font_min_pt",
    "line_spacing": "line_spacing",
    "margins": "margins_cm",
    "signature_required": "signed_declaration",
}


@dataclass(frozen=True)
class Slotted:
    """What the first request settled about one sentence: who and what."""

    index: int
    document: Document
    document_confidence: float
    operation: Operation
    operation_confidence: float
    third_party: bool
    conditional: bool


@dataclass(frozen=True)
class Rule:
    """One filled rule, or one note. `note` empty means it is applied.

    `sentence` is verbatim page text and becomes `rule_text`; `heading` is the
    context the question was asked with and is stored so §6.5's re-derivation
    can ask again without the page (spec §9a).
    """

    index: int
    document: Document
    operation: RuleOperation
    value: object
    sentence: str
    heading: str = ""
    unit: str = ""
    #: The style value's own sub-value, where it has one: the font family the
    #: sentence names, a point size, a line spacing, a margin. It is PICKED from
    #: the sentence like any other value (grammar_values), never generated --
    #: which is why it is a field here and not a free string a caller fills in.
    detail: str = ""
    confidence: float = 0.0
    #: "" when applied; otherwise one of §6.3's kinds or §6.5's `unapplied`:
    #: unsure | conflict | conditional | phrasing | third_party | unapplied | quarantined
    note: str = ""
    condition: str = ""
    probabilities: tuple[tuple[str, float], ...] = ()
    #: On a limit: maximum | minimum | approximate. On a topic cut from a
    #: length sentence: the NOTE_BOUNDS member its figure was. "" on everything
    #: else, and read as a cap by limit_sink's callers, which is the old
    #: single-length reading every pre-amendment test assumes.
    bound: str = ""
    #: Which figure of its sentence this rule is (letter_terms.figures_on_line's
    #: order). A range yields figures 0 and 1 from one sentence, so the index
    #: alone no longer names a rule. None when no figure produced the rule.
    figure: int | None = None
    #: On a character figure: True when the page counts WITHOUT spaces (the
    #: per-figure Noul, at the bar). Only the CV's key depends on it
    #: (limit_sink); the letter's cap and floor are each measured the stricter
    #: way whatever the page says.
    excl_spaces: bool = False

    @property
    def applied(self) -> bool:
        return not self.note


def sink_for(document: str, operation: str, value: object) -> str:
    """Where this rule lands, or "" when nothing downstream can carry it.

    "" is not an error: it is §6.5's `unapplied`, the honest answer when a page
    states a real requirement the engine has no handler for. It is counted, and
    the grammar grows from the count -- never from a model improvising.

    For a limit, `value` is the UNIT and the answer is the cap's sink; a caller
    that knows the figure's bound calls `limit_sink`.
    """
    if document == "reference_letter":
        # The referee's document. For the applicant it is one action: obtain it.
        return "student_actions"
    if document == "other":
        return ""
    if operation == "student_action":
        return "student_actions"
    if document == "cv":
        return _cv_sink(operation, value)
    if document == "motivation_letter":
        return _letter_sink(operation, value)
    return ""


def limit_sink(document: str, bound: str, unit: str, *, excl_spaces: bool = False) -> str:
    """Where one figure lands, or "" when nothing can carry it.

    A cap and an approximation land on the unit's max field; a floor lands on the
    letter's min_words / min_chars and nowhere else -- no CV checker measures a
    floor and nothing measures a page floor, so those are `unapplied`, shown and
    counted, never silently read as caps. `not_a_limit` and an unknown unit have
    no sink, and neither has a NOTE_BOUNDS figure -- it becomes a topic.
    `excl_spaces` (always `rule.excl_spaces`) only moves a CV character cap to
    its own key: the letter's one character cap is measured with spaces, the
    stricter reading.
    """
    if document == "reference_letter":
        return "student_actions"
    if bound == "minimum":
        return _LETTER_FLOOR_SINK.get(unit, "") if document == "motivation_letter" else ""
    if bound not in ("maximum", "approximate"):
        return ""
    if document == "cv":
        if unit == "characters" and excl_spaces:
            return "max_chars_excl_spaces"
        return _CV_LIMIT_SINK.get(unit, "")
    if document == "motivation_letter":
        return _LETTER_LIMIT_SINK.get(unit, "")
    return ""


def _cv_sink(operation: str, value: object) -> str:
    if operation == "limit":
        # The unit decides the key. Fix round 1, finding 4: an unknown unit
        # returns "" (unapplied), never a silent "max_pages" fallback -- agrees
        # with limit_sink, which never guessed a unit either.
        return _CV_LIMIT_SINK.get(str(value), "")
    if operation == "language":
        return "language"
    if operation == "format":
        return "cv_format_requirement" if value in FORMAT_VERDICTS else ""
    if operation == "style":
        return _CV_STYLE_SINK.get(str(value), "")
    if operation == "include":
        return "cv_directives" if value in _INCLUDE_TARGETS else ""
    if operation == "order":
        # The value is the (target, direction) pair grammar_values builds; a
        # bare target is half a directive and has no sink.
        if not (isinstance(value, tuple | list) and len(value) == 2):
            return ""
        target, direction = value
        return "cv_directives" if (
            target in _ORDER_TARGETS and direction in _ORDER_DIRECTIONS
        ) else ""
    if operation == "emphasise":
        return "cv_directives" if value in _SECTIONS else ""
    if operation == "coverage":
        return coverage_key(value)
    # `topic` has no CV sink: the CV states facts from the ledger and has no
    # free-text section a topic could steer. On the letter it does.
    return ""


def _letter_sink(operation: str, value: object) -> str:
    if operation == "limit":
        # Fix round 1, finding 4: an unknown unit returns "" (unapplied),
        # never a silent "max_pages" fallback -- agrees with limit_sink.
        return _LETTER_LIMIT_SINK.get(str(value), "")
    if operation == "language":
        # The letter's language lives on ApplicationPrompt.document_language,
        # written through LetterShape.document_language by apply_derived_shape
        # (addendum §6.4).
        return "document_language"
    if operation == "style":
        return _LETTER_STYLE_SINK.get(str(value), "")
    if operation == "topic":
        return "written_requirements"
    if operation == "format":
        # A letter has no Europass; a template it names is a student action
        # (download it, use it) until a renderer knows it.
        return "student_actions" if value == "other_template" else ""
    if operation == "form":
        return "form" if value in FORM_VALUES else ""
    if operation == "naming":
        return "naming" if value in NAMING_VALUES else ""
    return ""


#: Every sink this grammar may name -- exactly the values `sink_for` and
#: `limit_sink` can return, never a wider "any real constraint key" set.
#: Fix round 1, finding 3: the earlier formula unioned the WHOLE
#: `_CONSTRAINT_KEYS` type, so a key nothing here can name (`max_bytes`,
#: `undecided`, `unapplied`, `min_chars_excl_spaces` -- that one reached only
#: through `letter_shape._SHAPE_TO_KEY`, a step downstream of this grammar)
#: still validated as if the grammar could produce it. A test walks every
#: document x operation x value and every document x bound x unit the closed
#: lists allow and asserts this set is exactly what that walk produces.
SINKS: frozenset[str] = frozenset(
    {"cv_directives", "cv_format_requirement", "student_actions", "written_requirements",
     "document_language", "form", "naming", "language", "max_chars_excl_spaces",
     "cv_scope", "cv_start", "cv_item_cap", ""}
    | set(_CV_LIMIT_SINK.values())
    | set(_CV_STYLE_SINK.values())
    | set(_LETTER_LIMIT_SINK.values())
    | set(_LETTER_FLOOR_SINK.values())
    | set(_LETTER_STYLE_SINK.values())
)
