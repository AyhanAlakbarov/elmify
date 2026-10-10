"""Typed rules in, the sinks the engine already has out.

Design: docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md §6,
amended by 2026-09-26-requirement-reader-addendum-design.md §6.1.

Three parts: conflict resolution, the CV's own projection -- constraint rules,
directives, notes and the format switch -- and the letter's, one LetterShape. Nothing
here calls a model: by the time a rule reaches this module it is already
typed, and all that remains is to write it where the renderer, the generator
and the letter engine will find it.
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from apps.funding.models import Program

from .catalog_seed import GERMAN_GAP_TOLERANCE_MONTHS
from .constraints import ConstraintRule, Enforcement, _quote, check_directive_shape
from .grammar import (
    _IMPLAUSIBLE_CAP,
    _IMPLAUSIBLE_MAX,
    FORM_VALUES,
    NAMING_VALUES,
    Rule,
    limit_sink,
    sink_for,
)
from .letter_shape import (
    _SAFE_FONT_FAMILY,
    LetterShape,
    _form_decision,
    _naming_decision,
)

if TYPE_CHECKING:
    # Annotation only: grammar_questions imports nothing from here, but keeping
    # the request module out of the projection's run-time imports keeps this
    # module free of the decisions client.
    from .grammar_questions import PageFacts

logger = logging.getLogger(__name__)

#: Operations that hold ONE value per document. Two of these at the bar with
#: different values contradict each other. `include`, `emphasise`, `topic` and
#: `student_action` are set-valued -- a page may require three fields, name two
#: themes and ask for two actions, and none of that is a contradiction.
_SINGLE_VALUED = frozenset({"limit", "language", "format", "order"})

#: A format the page contradicts itself about falls back to `any`, the
#: no-egress default: a page that cannot make up its mind about Europass must
#: never resolve to the one action that moves student data (spec §6.2, §14).
_FORMAT_SAFE = "any"

# <!-- reconciled 2026-09-26: the last member is Rule.excl_spaces -->
Bucket = tuple[str, str, str, str, bool]


# <!-- amended 2026-09-26: the side (cap or floor) and the spaces reading are part
# of what two rules must share to contradict each other -->
def _bucket(rule: Rule) -> Bucket:
    """What a rule would have to match to contradict another.

    For a limit: the unit, because max_words and max_pages are different keys;
    the side, because a range's floor and cap are both true at once; and the
    CV's spaces reading, because max_chars_incl_spaces and max_chars_excl_spaces
    are different keys too. An approximation is a cap (grammar.BOUNDS). A
    NOTE_BOUNDS figure never reaches here: it is a `topic`, which is set-valued.
    """
    if rule.operation == "limit":
        side = "floor" if rule.bound == "minimum" else "cap"
        # <!-- reconciled 2026-09-26 -->
        return (rule.document, rule.operation, rule.unit, side, rule.excl_spaces)
    return (rule.document, rule.operation, "", "", False)


def _comparable(value: object) -> object:
    """A language rule allowing two languages is a list; compare it as a tuple."""
    return tuple(value) if isinstance(value, list) else value


def _safer(bucket: Bucket, values: set[object]) -> object:
    """The value that cannot break what the page requires, or None when no
    ordering makes one safer."""
    _, operation, _, side, _ = bucket
    if operation == "limit":
        # A cap: the smaller -- a letter inside two pages is inside three, and
        # the reverse gets an application rejected. A floor: the larger, for
        # the mirror reason (addendum §6.1).
        numbers = [v for v in values if isinstance(v, int | float)]
        return max(numbers) if side == "floor" else min(numbers)
    if operation == "format":
        return _FORMAT_SAFE
    # `language` and `order`: no ordering makes one safer, so the page states
    # nothing this engine can act on. The notes carry every side.
    return None


def _contends(rule: Rule) -> bool:
    """Whether a rule can contradict another: applied and single-valued. A
    `not_a_format_rule` value is the absence of a format verdict, not one, so it
    never joins a format dispute (fix round 1, finding 5)."""
    return (
        rule.applied and rule.operation in _SINGLE_VALUED
        and not (rule.operation == "format" and rule.value == "not_a_format_rule")
    )


def resolve_conflicts(rules: Sequence[Rule]) -> tuple[Rule, ...]:
    """Apply the safer value where a page contradicts itself; note every side.

    Only rules that are AT the bar can contradict each other. One already
    carrying a note is not asserting anything, so counting it would turn one
    uncertain sentence into two notes and hide the certain rule beside it.
    """
    applied: dict[Bucket, list[Rule]] = defaultdict(list)
    for rule in rules:
        if _contends(rule):
            applied[_bucket(rule)].append(rule)

    disputed: dict[Bucket, object] = {}
    for bucket, group in applied.items():
        values = {_comparable(r.value) for r in group}
        if len(values) <= 1:
            continue
        disputed[bucket] = _safer(bucket, values)
        logger.info("conflicting %s rules %s; applying %r", bucket[1],
                    sorted(map(str, values)), disputed[bucket])

    resolved: list[Rule] = []
    settled: set[Bucket] = set()
    for rule in rules:
        bucket = _bucket(rule)
        if not (_contends(rule) and bucket in disputed):
            resolved.append(rule)
            continue
        # Every side of the dispute becomes a note carrying its own sentence.
        resolved.append(replace(rule, note="conflict"))
        if bucket in settled:
            continue
        settled.add(bucket)
        # The safer value may be one no sentence stated -- `any` between two
        # Europass verdicts -- and then nothing is applied: the notes are the
        # whole answer, and format_decision reads them as any + UNDECIDED.
        winner = next(
            (r for r in applied[bucket] if _comparable(r.value) == disputed[bucket]), None
        )
        if winner is not None:
            resolved.append(replace(winner, note=""))
    return tuple(resolved)


#: A style value and the value its constraint key takes. The polarity matters:
#: `photo_forbidden` is photo_allowed=False, and writing True would silently
#: invert a funder's rule.
_STYLE_VALUE: dict[str, object] = {
    "photo_required": True,
    "photo_forbidden": False,
    "signature_required": True,
    "date_of_issue_required": True,
    "date_of_birth_forbidden": False,
    # "No gaps" read at catalog_seed's own DE tolerance (C-002), not a bare
    # zero: a page's "no gaps" used to project stricter than the country seed
    # for the same key, so resolve_rules' specificity (a same-enforcement
    # programme rule always wins) let an ordinary summer between two degrees
    # become a false gap warning on every German programme whose page said
    # "no gaps" (fix round 1, finding 1). A page stating its OWN tolerance
    # ("no gaps longer than 3 months") is still read at this figure, not that
    # one -- which on an ADVISORY check costs a warning, never a missed one.
    # ponytail: the page's own tolerance figure is not read; pick it from
    # style_number when a page's stated tolerance is measured to matter.
    "no_gaps": GERMAN_GAP_TOLERANCE_MONTHS,
    # The one token render._check_prohibited_content knows.
    "no_hyperlinks": ["hyperlinks"],
}

#: A megabyte as a byte count for max_bytes. Decimal, not 1,048,576: a cap is
#: held the stricter way (the smaller number), as the letter's caps are, so a
#: file that passes ours passes the page's under either reading.
_BYTES_PER_MEGABYTE = 1_000_000

#: The format verdict as a Program.CVFormatRequirement, or None where the engine
#: must not act. `other_template` is None because render.py's _funder_dispatch
#: knows only SISGP and RHODES: deriving a template it cannot render would route
#: every other funder to UnsupportedRenderVariant (CLAUDE.md).
_FORMAT_SWITCH: dict[str, str | None] = {
    "europass_required": Program.CVFormatRequirement.EUROPASS_REQUIRED,
    "europass_preferred": Program.CVFormatRequirement.EUROPASS_PREFERRED,
    "any": Program.CVFormatRequirement.ANY,
    "not_a_format_rule": None,
    "other_template": None,
}


def cv_limit_key(rule: Rule) -> str:
    """The constraint key a CV length figure writes, or "" when it is not a cap.

    `""` as the bound is a limit rule written before bounds existed, read as a
    cap; `approximate` is a cap, as the letter path always has read it. The CV
    has no floor key, so a floor is a real statement nothing downstream
    carries: `unapplied`.
    """
    return limit_sink("cv", rule.bound or "maximum", rule.unit, excl_spaces=rule.excl_spaces)


def _cv_rules(rules: Sequence[Rule]) -> list[Rule]:
    return [r for r in rules if r.document == "cv" and r.applied]


def _is_font(rule: Rule) -> bool:
    """font_family and font_size_minimum both write the one `font` key, and
    resolve_rules keeps the last of a key -- so a page may apply only one."""
    return rule.operation == "style" and sink_for("cv", "style", rule.value) == "font"


_DIRECTIVE_OPERATIONS = ("include", "order", "emphasise")


def _directive(rule: Rule, source_url: str) -> dict[str, object] | None:
    """The stored directive, or None when the rule's value does not have the
    shape the read side accepts. The unpacking is inside the try so a malformed
    value is a note, never a crash in the middle of a page read."""
    try:
        if rule.operation == "order":
            target, value = rule.value  # type: ignore[misc]
        else:
            target, value = str(rule.value), None
        check_directive_shape(rule.operation, target, value)
    except (TypeError, ValueError):
        return None
    return {
        "action": rule.operation, "target": target, "value": value,
        "rule_text": _quote(rule.sentence), "source_url": source_url,
    }


def to_constraint_rules(
    rules: Sequence[Rule], *, source_url: str
) -> tuple[ConstraintRule, ...]:
    """The CV's value rules as stored constraints.

    Format is not here: it is a switch on the Program, not a constraint key
    (`format_decision`). Directives are not here either (`to_directives`).
    Everything written is ADVISORY_HIGH_RISK, without exception -- a classifier
    answer can make a rule SAY "required" and can never make one BIND
    (2026-09-13 spec, CLAUDE.md).
    """
    built: list[ConstraintRule] = []
    font_taken = False
    for rule in _cv_rules(rules):
        if rule.operation in ("format", "include", "order", "emphasise",
                              "topic", "student_action", "form", "naming", "other"):
            continue
        key = (
            cv_limit_key(rule) if rule.operation == "limit"
            else sink_for("cv", rule.operation, rule.value)
        )
        if not key or key == "cv_directives":
            continue
        if key == "font":
            # The first font rule on the page is the constraint; each further
            # one is an `unapplied` note (to_notes), never a silent overwrite.
            if font_taken:
                continue
            font_taken = True
        if rule.operation == "style":
            # A flag style is its polarity; a detail style (font family, point
            # size) is the value the sentence printed, which `detail` carries.
            value = _STYLE_VALUE.get(str(rule.value), rule.detail or rule.value)
        elif key == "max_bytes" and isinstance(rule.value, int | float):
            # The page's figure, in the key's unit: an exact conversion.
            value = math.floor(rule.value * _BYTES_PER_MEGABYTE)
        else:
            value = rule.value
        built.append(ConstraintRule(
            rule_id=page_rule_id(rule.index, key),
            key=key,  # type: ignore[arg-type]
            value=value,
            enforcement=Enforcement.ADVISORY_HIGH_RISK,
            rule_text=_quote(rule.sentence),
            source_url=source_url,
            scope="PROGRAMME",
        ))
    return tuple(built)


def page_rule_id(index: int, key: str) -> str:
    """As much of the key as a rule_id holds (20 characters: CatalogRule and
    ConstraintOverride's column). A fixed nine-letter cut made
    max_chars_incl_spaces and max_chars_excl_spaces one id on one sentence,
    and ConstraintOverride is keyed on rule_id alone; every key stays distinct
    through index 999 (tests/documents/test_rule_sinks_cv.py)."""
    return f"PAGE-{index}-{key}"[:20]


def to_directives(rules: Sequence[Rule], *, source_url: str) -> tuple[dict[str, object], ...]:
    """The CV's structural rules as stored directives.

    `order` carries a (target, direction) pair; the others carry a target alone.
    Each is validated through `check_directive_shape`, the same function the
    read side runs, so a directive that would fail on read fails here instead
    -- and becomes an `unapplied` note (`to_notes`), never a silent drop.
    """
    built: list[dict[str, object]] = []
    for rule in _cv_rules(rules):
        if rule.operation not in _DIRECTIVE_OPERATIONS:
            continue
        directive = _directive(rule, source_url)
        if directive is None:
            logger.warning("a malformed %s directive is an unapplied note",
                           rule.operation)
            continue
        built.append(directive)
    return tuple(built)


def to_referee(rules: Sequence[Rule], *, source_url: str) -> tuple[dict[str, object], ...]:
    """The page's reference-letter facts, one record per field a sentence stated.

    Written to `Program.referee_requirements` and read by the student-dashboard's
    application-route catalogue. Each record carries its byte-exact sentence and
    the page it came from. A conditional fact is kept, marked, with the condition
    kind: "scholarship applicants also need..." is a route, and dropping it or
    applying it to everyone are both wrong. A field with no record was not stated.
    """
    records: list[dict[str, object]] = []
    for rule in rules:
        if rule.operation != "referee" or rule.note not in ("", "conditional"):
            continue
        field, value = cast(tuple[str, str], rule.value)
        records.append({
            "field": field, "value": value, "date": rule.detail,
            "conditional": rule.note == "conditional", "condition": rule.condition,
            "rule_text": _quote(rule.sentence), "source_url": source_url,
        })
    return tuple(records)


def to_notes(rules: Sequence[Rule], *, source_url: str) -> tuple[ConstraintRule, ...]:
    """Every note, as the `undecided` or `unapplied` rule the student reads.

    These are constraints._MULTI_KEYS: they carry a QUOTE rather than a value,
    have no checker, and `render_cv_with_warnings` puts them in front of the
    student with the page's own words (CLAUDE.md, "Who reads a CV warning").
    The rule_id names the sentence AND the kind, because one sentence can be
    undecided about several things at once and resolve_rules slots these by
    id -- a shared id silently drops all but one.

    Three CV shapes reach here even though the rule is APPLIED (no note),
    because nothing else in this module writes them anywhere and a written
    requirement with no home would otherwise vanish:

    - a length figure that is a floor (the CV has no floor key), or another
      NOTE_BOUNDS figure Task 6 already marked `unapplied` -- a section limit
      or another statement's length;
    - a format verdict of `other_template` (controller ruling C6): the switch
      maps it to None and `format_decision` writes `any` + UNDECIDED, but
      nothing wrote the sentence itself anywhere for the student to read,
      until now;
    - a `student_action` rule (controller ruling C7): `sink_for` names
      `student_actions`, a sink `to_constraint_rules` deliberately does not
      write to (it is not a CV constraint key), so without this branch the
      action the page asked for reached the student nowhere.

    Fix round 1 adds two more, for the same reason: a font rule after the
    page's first (they share the `font` key, finding 2) and a directive whose
    value fails the read side's shape (finding 4).

    One sentence gets one note per kind -- its figures share the quote, so a
    second would say the same thing twice.
    """
    built: list[ConstraintRule] = []
    seen: set[tuple[int, str]] = set()
    font_seen = False
    for rule in rules:
        if rule.operation == "referee":
            # A record of its own (to_referee), conditional ones included: the
            # route a condition names is the fact the catalogue needs.
            continue
        if rule.applied and rule.document == "other":
            continue
        # A NOTE guessed `other` is kept: a below-bar slot's document is only
        # its best guess, and a skipped sentence is silent (final review, I1).
        if rule.applied:
            is_cv = rule.document == "cv"
            is_extra_font = is_cv and _is_font(rule) and font_seen
            font_seen = font_seen or (is_cv and _is_font(rule))
            is_bad_directive = (
                is_cv and rule.operation in _DIRECTIVE_OPERATIONS
                and _directive(rule, source_url) is None
            )
            is_cv_floor = (
                rule.document == "cv" and rule.operation == "limit"
                and not cv_limit_key(rule)
            )
            is_other_template = (
                rule.document == "cv" and rule.operation == "format"
                and rule.value == "other_template"
            )
            is_cv_student_action = rule.document == "cv" and rule.operation == "student_action"
            if is_other_template:
                kind = "undecided"
            elif is_cv_floor or is_cv_student_action or is_extra_font or is_bad_directive:
                kind = "unapplied"
            else:
                continue
        else:
            kind = rule.note
        if (rule.index, kind) in seen:
            continue
        seen.add((rule.index, kind))
        built.append(ConstraintRule(
            rule_id=f"PAGE-{rule.index}-{kind[:9]}",
            key="unapplied" if kind == "unapplied" else "undecided",
            value=f"{rule.document}:{rule.operation}",
            enforcement=Enforcement.ADVISORY_HIGH_RISK,
            rule_text=_quote(rule.sentence),
            source_url=source_url,
            scope="PROGRAMME",
        ))
    return tuple(built)


def format_decision(rules: Sequence[Rule]) -> tuple[str, str]:
    """The Program's format switch and its confidence.

    A page that states no format rule writes `any` + EXTRACTED: with selection
    over enumerated sentences, silence is the page's and is a result (spec §5.3).
    A format rule that could not be settled -- a phrasing disagreement, a
    conflict, a template the engine does not know -- writes `any` + UNDECIDED,
    the no-egress default, and its sentence is already a note (`to_notes`).

    This is the last gate before a Europass action ships a student's name, date
    of birth, education and employment history to europa.eu, so it holds on its
    own and never assumes `resolve_conflicts` ran (fix round 1, finding 1): a
    switch is written only when every applied format value is the same one and
    no format sentence is unsettled. A `third_party` note is about someone
    else's CV and unsettles nothing; `not_a_format_rule` is no verdict at all.
    """
    formats = [r for r in rules if r.document == "cv" and r.operation == "format"]
    values = {
        str(r.value) for r in formats if r.applied and r.value != "not_a_format_rule"
    }
    notes = [r.note for r in formats if not r.applied]
    unsettled = [n for n in notes if n != "third_party"]
    # Any unsettled sentence naming Europass, whatever its slot guessed: a
    # below-bar "Europass CV is not accepted." read as `other` must not leave
    # the page's Europass requirement standing alone (final review, I1).
    europass_unsettled = any(
        not r.applied and r.note != "third_party" and "europass" in r.sentence.casefold()
        for r in rules
    )
    if len(values) == 1 and not unsettled and not europass_unsettled:
        switch = _FORMAT_SWITCH.get(next(iter(values)))
        if switch is not None:
            return switch, Program.CVFormatConfidence.EXTRACTED
    if values or notes or europass_unsettled:
        return Program.CVFormatRequirement.ANY, Program.CVFormatConfidence.UNDECIDED
    return Program.CVFormatRequirement.ANY, Program.CVFormatConfidence.EXTRACTED


#: A letter style value and the LetterShape field it sets, for the booleans.
_LETTER_FLAG: dict[str, str] = {
    "signed_declaration": "signed_declaration",
    "signature_required": "signed_declaration",
    "handwritten": "handwritten",
}
#: The plausibility bands' key for each unit (grammar._IMPLAUSIBLE_*).
_BAND: dict[str, str] = {"pages": "pages", "words": "words", "characters": "chars"}
#: The line spacings LetterVerdict allowed, kept rather than trusting a picked
#: number more than the frontier path trusted a generated one.
_LINE_SPACINGS = (1.0, 1.5, 2.0)
#: Fix round 1, finding 2: `style_number` picks the FIGURE, never its unit, so
#: "1 inch" and "2.5 cm" both arrive as a bare number in `rule.detail`. Reading
#: either as centimetres is a wrong value in the unsafe direction (an inch held
#: as a centimetre is a much narrower margin than the page asked for), so the
#: unit is read off the sentence itself: only cm, or mm converted by an exact
#: ÷10 (the figure is still the page's own), may set `margins_cm`. Any other or
#: missing unit is not silently narrowed -- it is a written requirement.
#: Preceded by a digit or space (never a letter, so "recommend" and "comment"
#: never match) and followed by a word boundary: a page prints "2.5cm" with no
#: space at least as often as "2.5 cm".
_MARGIN_UNIT = re.compile(r"(?<=[\d\s])(cm|mm)\b", re.IGNORECASE)
#: When two sentences set one field, which value is safer. A cap: the smaller.
#: A floor, a minimum font size, a margin, a line spacing: the larger. Anything
#: else keeps the first sentence that set it.
_SMALLER_IS_SAFER = frozenset({"max_words", "max_chars", "max_pages"})
_LARGER_IS_SAFER = frozenset({"min_words", "min_chars", "font_min_pt", "margins_cm",
                              "line_spacing"})


def letter_field(rule: Rule) -> tuple[str, object] | None:
    """Where one applied letter rule lands: a LetterShape field and its value,
    `written_requirements` or `student_actions` with the sentence, or None.

    `form` and `naming` come back in the grammar's own lowercase values;
    `to_letter_shape` resolves them into LetterShape's uppercase ones. Task
    11's letter gate scores through this function, so the gate measures the
    projection that ships rather than a copy of it.
    """
    if not rule.applied:
        # Controller ruling C3: a conditional, third-party or unsure rule is a
        # note and never sets a field.
        return None
    if rule.operation == "referee":
        # The sentence already reaches student_actions through its own rule;
        # the referee facts are records on the programme (to_referee).
        return None
    if rule.document == "reference_letter":
        # The referee's document. For the applicant it is one action: obtain it.
        return ("student_actions", rule.sentence)
    if rule.document != "motivation_letter":
        return None
    operation = rule.operation
    if operation == "student_action":
        return ("student_actions", rule.sentence)
    if operation == "topic":
        return ("written_requirements", rule.sentence)
    if operation == "format":
        # A letter has no Europass; a template it names is the student's to use.
        return ("student_actions", rule.sentence) if rule.value == "other_template" else None
    if operation == "form":
        return ("form", rule.value) if rule.value in FORM_VALUES else None
    if operation == "naming":
        return ("naming", rule.value) if rule.value in NAMING_VALUES else None
    if operation == "language":
        # ApplicationPrompt.document_language holds ONE code, so a page allowing
        # several needs a pick: English when it is allowed, otherwise the first.
        # Every allowed one satisfies the page; the sentence in `sources` shows
        # what else was on offer.
        allowed = rule.value if isinstance(rule.value, list) else [rule.value]
        if not allowed or not all(isinstance(code, str) and code for code in allowed):
            return None
        return ("document_language", "en" if "en" in allowed else allowed[0])
    if operation == "limit":
        return _letter_limit(rule)
    if operation == "style":
        return _letter_style(rule)
    return None


def _letter_limit(rule: Rule) -> tuple[str, object] | None:
    """One figure onto its bound's field (addendum §6.1, §6.2).

    `limit_sink` is the one mapping: a cap or an approximation onto max_*, a
    floor onto min_words / min_chars. A cap counted without spaces is held as
    the same number WITH spaces and a floor is always counted without them --
    each the stricter reading, so a letter that passes ours passes theirs.
    Tolerances, section limits and a second statement never get here: they
    arrive as topics.

    Fix round 1, finding 3: a page floor (a minimum stated in pages -- no
    field holds one) never reaches this function applied. `grammar_values`
    runs this same `limit_sink` check before building the Rule at all
    (`_has_sink`) and marks it `unapplied` there, so `letter_field` returns
    None for it before `_letter_limit` is ever called -- the
    `written_requirements` fallback below cannot see it. It surfaces through
    `to_notes` instead, as an `unapplied` note carrying its sentence
    (`tests/documents/test_rule_sinks_letter.py::
    test_a_letter_page_floor_is_marked_unapplied_before_this_module_sees_it`,
    fed through `read_values` for real). The fallback below still matters for
    a unit nothing measures at all and for a Rule built directly, as this
    module's own other tests do.

    The number is the page's figure, copied: pages stay fractional (C8 -- half
    a page is not 0), and words and characters are whole, a fraction rounded
    toward the stricter side, which only a misread could produce anyway.
    """
    floor = rule.bound == "minimum"
    unit = rule.unit
    name = limit_sink("motivation_letter", rule.bound or "maximum", unit,
                      excl_spaces=rule.excl_spaces)
    if not name or not isinstance(rule.value, int | float):
        # No field holds it (a page floor, a unit nothing measures): the writer
        # reads the sentence, never silence.
        return ("written_requirements", rule.sentence)
    band = _BAND[unit]
    number = rule.value
    if number > _IMPLAUSIBLE_MAX[band] or (not floor and number < _IMPLAUSIBLE_CAP[band]):
        logger.warning("ignoring an implausible %s %s of %s on a programme page",
                       band, "floor" if floor else "cap", number)
        return None
    if unit == "pages":
        return (name, float(number))
    return (name, math.ceil(number) if floor else math.floor(number))


def _letter_style(rule: Rule) -> tuple[str, object] | None:
    """One style value onto its LetterShape field, inside the ranges LetterVerdict enforced.

    Fix round 1, finding 1: a value LetterShape cannot hold -- a spacing
    besides 1.0/1.5/2.0 (Task 6 deliberately offers 1.15 as a candidate), or a
    font size or margin outside LetterVerdict's own range -- is not silently
    dropped. It is a real, page-stated requirement nothing here enforces, so
    it is kept as a written requirement (the same answer `_letter_limit` gives
    a page floor), with a warning naming the value for font size and margin,
    where the number itself may be a misread digit rather than a genuine
    outlier.
    """
    value = str(rule.value)
    if value in _LETTER_FLAG:
        return (_LETTER_FLAG[value], True)
    if value == "font_family":
        if _SAFE_FONT_FAMILY.fullmatch(rule.detail):
            return ("font_family", rule.detail)
        logger.warning("dropping an unsafe font family from %r", rule.sentence[:80])
        return None
    if value not in ("font_size_minimum", "margins", "line_spacing"):
        # A CV-only style (photo, date of birth) has no letter field, and
        # `single_file_bundle` has no reader (grammar._LETTER_STYLE_SINK):
        # Task 6 already marked both unapplied, so nothing reaches here applied.
        return None
    try:
        number = float(rule.detail)
    except ValueError:
        logger.warning("dropping an unreadable %s from %r", value, rule.sentence[:80])
        return None
    if value == "line_spacing":
        # spacing_candidates offers the figure as printed, so "2" arrives as
        # well as "2.0"; compared as a number, never as a string.
        if number in _LINE_SPACINGS:
            return ("line_spacing", number)
        return ("written_requirements", rule.sentence)
    if value == "font_size_minimum":
        if 4 <= number <= 40:
            # Up, never down: a 10.5pt minimum held as 10 is under the page's.
            return ("font_min_pt", math.ceil(number))
        logger.warning("a minimum font size of %s is outside 4-40pt; keeping %r as a "
                       "written requirement", number, rule.sentence[:80])
        return ("written_requirements", rule.sentence)
    # value == "margins": finding 2. `number` (the page's own figure) is only
    # ever centimetres or an exact ÷10 of millimetres -- never guessed from an
    # inch or an unstated unit, which would be a narrower margin than stated.
    unit = _margin_unit(rule.sentence)
    if unit is None:
        return ("written_requirements", rule.sentence)
    centimetres = number / 10 if unit == "mm" else number
    if 0.1 <= centimetres <= 10:
        return ("margins_cm", centimetres)
    logger.warning("a margin of %scm is outside 0.1-10cm; keeping %r as a written requirement",
                   centimetres, rule.sentence[:80])
    return ("written_requirements", rule.sentence)


def _margin_unit(sentence: str) -> str | None:
    """"cm" or "mm" if the sentence names one, else None.

    An inch, or no unit at all, must not be read as a centimetre -- that is a
    wrong value in the unsafe direction (finding 2). `cm` wins if a sentence
    somehow names both, since it needs no conversion.
    """
    units = {m.group(1).lower() for m in _MARGIN_UNIT.finditer(sentence)}
    if "cm" in units:
        return "cm"
    if "mm" in units:
        return "mm"
    return None


def to_letter_shape(
    rules: Sequence[Rule], *, source_url: str, page: PageFacts | None = None
) -> LetterShape:
    """The letter's rules, and the page's letter facts, as the shape the letter engine consumes.

    Every field the frontier path types is written here too (addendum §6.3),
    with `document_language` and `min_chars`. `form` and `naming` resolve with
    the frontier path's own functions, so the two paths cannot disagree about
    the safer side; those functions take the grammar's lowercase values and
    return LetterShape's uppercase ones. `document_required` is written only
    with an applied letter sentence as its witness -- a flag with no sentence
    is a decision nobody can check (spec §6.4).
    """
    fields: dict[str, object] = {}
    sources: dict[str, dict[str, str]] = {}
    written: list[dict[str, str]] = []
    actions: list[dict[str, str]] = []
    forms: list[Rule] = []
    namings: list[Rule] = []

    def cite(rule: Rule) -> dict[str, str]:
        return {"text": rule.sentence, "source_url": source_url}

    for rule in rules:
        target = letter_field(rule)
        if target is None:
            continue
        name, value = target
        if name in ("written_requirements", "student_actions"):
            bucket = written if name == "written_requirements" else actions
            if cite(rule) not in bucket:
                bucket.append(cite(rule))
        elif name == "form":
            forms.append(rule)
        elif name == "naming":
            namings.append(rule)
        elif name not in fields or (
            (name in _SMALLER_IS_SAFER and value < fields[name])  # type: ignore[operator]
            or (name in _LARGER_IS_SAFER and value > fields[name])  # type: ignore[operator]
        ):
            fields[name] = value
            sources[name] = cite(rule)

    if forms:
        values = {str(r.value) for r in forms}
        # Controller ruling C9: PORTAL_FORM only when it is the ONLY form the
        # page states. A portal sentence beside an essay one is FORMAL_LETTER.
        decided = _form_decision(values, portal_unanimous=values == {"portal_form"})
        fields["form"] = decided
        # The sentence that decided it: the one stating the winning form, or,
        # for a FORMAL_LETTER no sentence named, the portal sentence that
        # tipped an essay into one.
        witness = [decided.lower(), "portal_form"]
        sources["form"] = cite(min(
            forms, key=lambda r: witness.index(str(r.value)) if r.value in witness else 2
        ))
    if namings:
        votes = [str(r.value) for r in namings]
        decided = _naming_decision(votes, len(votes))
        fields["naming"] = decided
        sources["naming"] = cite(
            next((r for r in namings if str(r.value) == decided.lower()), namings[0])
        )
    if page is not None:
        witness_rule = next(
            (r for r in rules if r.document == "motivation_letter" and r.applied), None
        )
        if page.letter_required != "UNSTATED" and witness_rule is not None:
            fields["document_required"] = page.letter_required
            sources["document_required"] = cite(witness_rule)
        if page.track:
            fields["track"] = page.track
        if page.portfolio_led:
            fields["portfolio_led"] = True

    return LetterShape(
        **fields,  # type: ignore[arg-type]
        sources=sources,
        written_requirements=tuple(written),
        student_actions=tuple(actions),
    )
