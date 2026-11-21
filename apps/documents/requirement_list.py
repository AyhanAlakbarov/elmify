"""The requirement list: every CV and letter requirement for one application,
gathered and merged before anything is written.

Spec: docs/superpowers/specs/2026-10-12-cv-engine-quality-design.md §6.3-§6.4.

Pure. Nothing here reads the database or calls a model: `build_requirements`
takes what its caller loaded, `merge` applies §6.4 steps 1-7, and
`RequirementList.cv_rules` projects the CV items back onto the ConstraintRule
tuple render already reads -- `constraints.resolve_rules` is that projection,
so render and the list cannot disagree. Step 8, the privacy check before
europa.eu, is render.py's (`without_banned_content`), reading the projection.

A page's sentence rides on an item for DISPLAY only (`sentence`). Nothing in
this module puts it anywhere a writer reads: the typed key and value are the
instruction, and page text is shared by every tenant.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from .constraints import (
    _SCOPE_ORDER,
    CONSTRAINT_KEYS,
    QUOTE_MAX_CHARS,
    READINGS_MAX,
    ConstraintRule,
    Enforcement,
    PageDirective,
    SavedReadings,
    _quote,
    _scope_matches,
    directives_from_program,
    rules_from_program,
)

if TYPE_CHECKING:
    from .letter_shape import LetterShape

Document = Literal["cv", "letter"]
Origin = Literal["programme", "scholarship", "institution", "ours"]
Force = Literal["strict", "soft", "info"]
#: Spec §6.8's states, one per item id on DocumentDraft.requirement_states.
#: Every id starts `pending`; build step 4.5 sets the rest.
ItemState = Literal[
    "pending", "applied", "translated", "left_out", "waiting_for_you", "not_fully_met",
    "choose_what_to_drop", "not_possible_yet", "official_template", "for_information",
    "temporary_error",
]

#: Theirs, in theirs-first order: the programme's own page, then the
#: scholarship, then our research about the university (spec §6.3).
THEIRS: tuple[Origin, ...] = ("programme", "scholarship", "institution")

#: A catalog scope's origin. INSTITUTION and FUNDER are theirs; the rest are ours.
_ORIGIN_BY_SCOPE: dict[str, Origin] = {
    "UNIVERSAL": "ours", "TRACK": "ours", "COUNTRY": "ours",
    "INSTITUTION": "institution", "FUNDER": "scholarship",
}

DIRECTIVE_ACTIONS: tuple[str, ...] = ("include", "order", "emphasise")

#: The LetterShape fields that are an item of their own. The five length fields
#: arrive as constraint keys through `letter_shape.constraints_from_shape`, and
#: `sources`, `written_requirements`, `student_actions`, `track` and
#: `portfolio_led` are not requirements. Pinned to LetterShape by test.
LETTER_FIELD_KEYS: tuple[str, ...] = (
    "document_required", "form", "signed_declaration", "naming", "font_family", "font_min_pt",
    "line_spacing", "margins_cm", "file_bundle", "handwritten", "document_language",
)

#: The for-information keys render is built to surface. Any other info item
#: stays on the list for display and never reaches render's checks.
_RENDERED_INFO_KEYS = frozenset({"ai_use_policy", "undecided", "unapplied"})

REQUIREMENT_KEYS: frozenset[str] = frozenset(
    CONSTRAINT_KEYS
    | set(DIRECTIVE_ACTIONS)
    | {"cv_format", "competency", "written_requirement", "student_action"}
    | set(LETTER_FIELD_KEYS)
)


class Requirement(BaseModel):
    """One item on an application's requirement list (spec §6.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: 16 hex characters, stable across rebuilds of the same application
    #: (spec §6.12); filled by `RequirementList`, never by a caller.
    id: str = Field(default="", max_length=16)
    key: str
    value: object = None
    document: Document
    origin: Origin
    force: Force
    #: The rule this item projects onto for render: the rule that supplied the
    #: value, carrying the merged value and the strongest contributor's
    #: enforcement. None for a directive, the format, a competency and a letter
    #: field, which render reads elsewhere.
    rule: ConstraintRule | None = None
    #: The rule_id of every rule merged into this item, the supplier first.
    contributors: tuple[str, ...] = ()
    #: The page's own sentence and URL, for display only (spec §6.6).
    sentence: str = Field(default="", max_length=QUOTE_MAX_CHARS)
    source_url: str = Field(default="", max_length=2048)
    #: An unclear sentence about a personal item: asked of the student (step 2).
    ask: bool = False
    #: Non-empty on every side of a requirement no one CV can meet; the value
    #: names the clash ("language", "photo_required+photo_allowed"). Build step
    #: 4.5 makes two versions or shows the student the choice (step 6).
    conflict: str = ""
    #: A COMPETENCY statement: ranks relevance (spec §7.2), never passes or fails.
    relevance_only: bool = False

    @model_validator(mode="before")
    @classmethod
    def _refill_sentence(cls, data: Any) -> Any:
        """A dump drops `sentence` when it duplicates the rule's; refill it
        on the way back in, so a stored row still shows its page sentence."""
        if not isinstance(data, dict) or data.get("sentence"):
            return data
        rule = data.get("rule")
        rule_text = (
            rule.get("rule_text") if isinstance(rule, dict) else getattr(rule, "rule_text", None)
        )
        return {**data, "sentence": rule_text} if rule_text else data

    @model_validator(mode="after")
    def _closed_key(self) -> Requirement:
        if self.key not in REQUIREMENT_KEYS:
            raise ValueError(f"{self.key!r} is not a requirement key")
        return self

    @model_serializer(mode="wrap")
    def _drop_duplicate_sentence(
        self, handler: Callable[[Requirement], dict[str, Any]]
    ) -> dict[str, Any]:
        """One stored sentence: a page's wording already lives on `rule`, so
        an identical item-level copy is never written twice."""
        dumped = handler(self)
        if self.rule is not None and self.sentence == self.rule.rule_text:
            dumped.pop("sentence", None)
        return dumped


class RequirementList(BaseModel):
    """One application's list, saved on `DocumentDraft.requirements` alongside
    `requirements_digest` and `requirement_states` (build step 4.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[Requirement, ...] = ()

    @model_validator(mode="after")
    def _assign_ids(self) -> RequirementList:
        """Spec §6.12: a lasting id per item, stable across rereads of the
        same page. The five-tuple below never includes `rule.rule_id` --
        that carries the sentence's position on the page, which a reread can
        renumber -- so a page rewrite that only moves things around keeps
        every item's id. `n` tells true duplicates (same five-tuple) apart."""
        counts: dict[str, int] = {}
        assigned: list[Requirement] = []
        changed = False
        for item in self.items:
            source_url = item.source_url or (item.rule.source_url if item.rule else "")
            identity = json.dumps(
                [item.document, item.key, item.origin, source_url, item.value],
                sort_keys=True, default=str,
            )
            n = counts.get(identity, 0)
            counts[identity] = n + 1
            digest_input = json.dumps(
                [item.document, item.key, item.origin, source_url, item.value, n],
                sort_keys=True, default=str,
            )
            item_id = hashlib.sha256(digest_input.encode()).hexdigest()[:16]
            if item.id != item_id:
                item = item.model_copy(update={"id": item_id})
                changed = True
            assigned.append(item)
        # `self` is frozen; a top-level `model_validator(mode="after")` run via
        # __init__ cannot return a different instance, so the fill-in mutates
        # in place through pydantic's own frozen-model escape hatch.
        if changed:
            object.__setattr__(self, "items", tuple(assigned))
        return self

    def digest(self) -> str:
        """Spec §6.12: changes exactly when something that changes the CV
        does -- not when a sentence's wording or its contributors change.

        Rows sort by their own JSON text rather than as raw lists: `value`
        can be a dict (`max_entries_per_section`), and two rows whose
        document/key/value differ only in an unordered type would otherwise
        raise comparing them directly.
        """
        rows = [
            [item.document, item.key, item.value, item.force, item.origin, item.conflict]
            for item in self.items
        ]
        rows.sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
        return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()

    def by_id(self) -> dict[str, Requirement]:
        return {item.id: item for item in self.items}

    def for_document(self, document: Document) -> tuple[Requirement, ...]:
        return tuple(item for item in self.items if item.document == document)

    def conflicts(self) -> dict[str, tuple[Requirement, ...]]:
        """Each irreconcilable clash and its sides, for step 6."""
        grouped: dict[str, list[Requirement]] = {}
        for item in self.items:
            if item.conflict:
                grouped.setdefault(item.conflict, []).append(item)
        return {name: tuple(sides) for name, sides in grouped.items()}

    def cv_rules(self) -> tuple[ConstraintRule, ...]:
        """The CV's items as the rules render checks: what resolve_rules returns.

        For-information items are left out (a losing `font` value would be
        reported as an unmet rule), except `_RENDERED_INFO_KEYS`.
        """
        return tuple(
            item.rule
            for item in self.items
            if item.document == "cv"
            and item.rule is not None
            and (item.force != "info" or item.key in _RENDERED_INFO_KEYS)
        )

    def cv_directives(self) -> tuple[PageDirective, ...]:
        """The non-conflicting CV directives (`include`, `emphasise`, `order`)
        saved on this list, so generation and rendering read the merged list
        rather than re-reading `Program.cv_directives` live."""
        directives: list[PageDirective] = []
        for item in self.items:
            if item.document != "cv" or item.conflict or item.force == "info":
                continue
            if item.key in ("include", "emphasise") and isinstance(item.value, str):
                action: Literal["include", "emphasise"] = (
                    "include" if item.key == "include" else "emphasise"
                )
                directives.append(
                    PageDirective(
                        action=action,
                        target=item.value,
                        value=None,
                        rule_text=item.sentence or "Requirement list directive.",
                        source_url=item.source_url,
                    )
                )
            elif (
                item.key == "order"
                and isinstance(item.value, list)
                and len(item.value) == 2
                and isinstance(item.value[0], str)
                and item.value[1] in ("chronological", "reverse_chronological")
            ):
                order_val: Literal["chronological", "reverse_chronological"] = (
                    "chronological"
                    if item.value[1] == "chronological"
                    else "reverse_chronological"
                )
                directives.append(
                    PageDirective(
                        action="order",
                        target=item.value[0],
                        value=order_val,
                        rule_text=item.sentence or "Requirement list directive.",
                        source_url=item.source_url,
                    )
                )
        return tuple(directives)

    def cv_competencies(self) -> tuple[str, ...]:
        """Competency statements saved on this list for skill tailoring."""
        return tuple(
            item.sentence
            for item in self.items
            if item.document == "cv" and item.key == "competency" and item.sentence
        )


@dataclass(frozen=True)
class Contribution:
    """One stored rule, before merging: where it came from and its scope rank."""

    rule: ConstraintRule
    origin: Origin
    document: Document = "cv"
    #: Ours only: the catalog scope's index in constraints._SCOPE_ORDER, -1 for
    #: a style rule the engine holds in code, which any catalog rule outranks.
    rank: int = 0


class Irreconcilable(ValueError):
    """Theirs state values no one CV can meet (spec §6.4 step 6)."""


# --- the "Stricter means" table (spec §6.4) ----------------------------------


def _per_section_lower(values: list[Any]) -> object:
    merged: dict[str, int] = {}
    for value in values:
        for section, limit in dict(value).items():
            merged[section] = min(int(limit), merged.get(section, int(limit)))
    return merged


def _union(values: list[Any]) -> object:
    combined: list[object] = []
    for value in values:
        combined.extend(item for item in value if item not in combined)
    return combined


def _forbid_wins(values: list[Any]) -> object:
    return not any(value is False for value in values)


def _required_wins(values: list[Any]) -> object:
    return any(value is True for value in values)


def _common_language(values: list[Any]) -> object:
    # Codes compare lowercased: "EN" and "en" are one language (final review M5).
    accepted = [
        [str(code).lower() for code in (value if isinstance(value, list) else [value])]
        for value in values
    ]
    common = [code for code in accepted[0] if all(code in other for other in accepted[1:])]
    if not common:
        raise Irreconcilable("no language every source accepts")
    return common if len(common) > 1 else common[0]


def _complete_wins(values: list[Any]) -> object:
    return "complete" if "complete" in values else "relevant_only"


def _earliest_start(values: list[Any]) -> object:
    if any(isinstance(v, dict) and "start" in v for v in values):
        reach = {"upper_secondary": 3, "first_degree": 2, "last_n_years": 1}
        start, years = "", 0
        for value in values:
            if not isinstance(value, dict):
                continue
            kind = str(value.get("start") or value.get("milestone") or "")
            n = value.get("years", 0)
            if not kind and isinstance(n, int) and n > 0:
                kind = "last_n_years"
            if kind not in reach:
                continue
            if kind == "last_n_years" and not (isinstance(n, int) and n > 0):
                continue
            if (
                not start
                or reach[kind] > reach[start]
                or (kind == start == "last_n_years" and isinstance(n, int) and n > years)
            ):
                start, years = kind, (n if kind == "last_n_years" and isinstance(n, int) else 0)
        if not start:
            return values[0]
        return {"start": start, "years": years} if start == "last_n_years" else {"start": start}
    milestones = {value.get("milestone") for value in values}
    milestone = next((m for m in ("upper_secondary", "first_degree") if m in milestones), None)
    legacy_years = max((value["years"] for value in values if value.get("years")), default=None)
    return {"milestone": milestone, "years": legacy_years}


_COMBINE: dict[str, Callable[[list[Any]], object]] = {
    "lower": min,
    "higher": max,
    "per_section_lower": _per_section_lower,
    "union": _union,
    "forbid_wins": _forbid_wins,
    "required_wins": _required_wins,
    "common_language": _common_language,
    "complete_wins": _complete_wins,
    "earliest_start": _earliest_start,
}

#: Rows handled outside `_COMBINE`: each contribution its own item (`info`,
#: `all_kept`), one item per direction per section (`one_direction`), and the
#: format, which keeps today's order instead of strictness (`format`).
_OTHER_ROWS = frozenset({"info", "all_kept", "one_direction", "format", "first"})

#: Every requirement key and the row of the table that merges it. A test fails
#: when a key exists without a row (spec §6.4, last paragraph).
#:
#: PII boundary: every derived page rule is ADVISORY, and
#: render._blocked_by_content_only_rules inspects BINDING rules only. So every
#: key in render._CONTENT_ONLY_KEYS -- date_of_issue_required above all, which
#: a Europass render can never carry -- must keep a strictness row here and the
#: strongest force (`_strongest`), never "info" or "first", or a page sentence
#: could open the EUROPASS_API egress. Pinned by
#: test_requirement_list.py::test_no_content_only_key_merges_as_information_or_first_seen.
MERGE: dict[str, str] = {
    "max_pages": "lower",
    "max_bytes": "lower",
    "no_unexplained_gaps": "lower",
    "max_words": "lower",
    "max_chars_incl_spaces": "lower",
    "max_chars_excl_spaces": "lower",
    "min_final_page_fill": "higher",
    "min_words": "higher",
    "min_chars_excl_spaces": "higher",
    "max_entries_per_section": "per_section_lower",
    "required_fields": "union",
    "prohibited_content": "union",
    "photo_allowed": "forbid_wins",
    "date_of_birth_allowed": "forbid_wins",
    "photo_required": "required_wins",
    "signature_required": "required_wins",
    "date_of_issue_required": "required_wins",
    "language": "common_language",
    "cv_scope": "complete_wins",
    "cv_start": "earliest_start",
    "cv_item_cap": "all_kept",
    "font": "first",
    "ai_use_policy": "info",
    # One item per sentence: the quote is the rule.
    "undecided": "info",
    "unapplied": "info",
    "include": "all_kept",
    "emphasise": "all_kept",
    "order": "one_direction",
    "cv_format": "format",
    "competency": "info",
    "written_requirement": "all_kept",
    "student_action": "all_kept",
    **dict.fromkeys(LETTER_FIELD_KEYS, "first"),
}

#: Step 2: the keys an unclear sentence is read stricter on -- limits and bans.
STRICTER_READING_KEYS: frozenset[str] = frozenset({
    "max_pages", "max_bytes", "no_unexplained_gaps", "max_entries_per_section",
    "min_final_page_fill", "prohibited_content", "max_words", "max_chars_incl_spaces",
    "max_chars_excl_spaces", "min_words", "min_chars_excl_spaces",
})
#: Step 2: the keys an unclear sentence is asked of the student about.
ASK_KEYS: frozenset[str] = frozenset({
    "photo_allowed", "photo_required", "date_of_birth_allowed", "signature_required",
    "required_fields",
})


def saved_readings(key: str, values: Sequence[object]) -> SavedReadings | None:
    """What an `undecided` rule keeps of its readings, or None.

    None for a key step 2 never reads, and for more values than SavedReadings
    holds: "any official EU language" read as fourteen codes raised
    ValidationError out of derive.decide and lost the whole page's read, where
    it is one for-information sentence (final review I1). One function for
    every writer -- derive's judge and rule_sinks' notes.
    """
    if key not in STRICTER_READING_KEYS | ASK_KEYS or not values or len(values) > READINGS_MAX:
        return None
    return SavedReadings.model_validate({"key": key, "values": tuple(values)})


def _fits(key: str, value: object) -> bool:
    """Whether `value` has the shape its strictness row compares (final review I2).

    A stored value is a model's answer, so its type is a claim: one "3"
    beside a 2 raised TypeError out of min() on every render of the
    programme, and a True became a one-page cap. The keys step 2 reads
    stricter and the two list keys are checked; every other row tolerates any
    value or raises, which `_merge_key` catches.
    """
    if MERGE.get(key) in ("required_wins", "forbid_wins"):
        # Only a real bool: render tests truthiness, so a BINDING `1` merged
        # by `is True` would read as False and open the Europass gate.
        return isinstance(value, bool)
    if key == "max_entries_per_section":
        return isinstance(value, dict) and bool(value) and all(
            isinstance(section, str) and isinstance(limit, int)
            and not isinstance(limit, bool) and limit >= 1
            for section, limit in value.items()
        )
    if key in ("prohibited_content", "required_fields"):
        # A union over a bare string unions its letters.
        return isinstance(value, list) and all(isinstance(token, str) for token in value)
    if key in STRICTER_READING_KEYS:
        # A tolerance of no months at all is a real gap rule; a cap of zero is not.
        # bool is an int: True is no page count (final review I2). Limits are
        # whole units, so a fractional cap like 0.5 is no reading either.
        # min_final_page_fill is the one fractional key: 0.2 is a real reading.
        return (
            isinstance(value, int | float) and not isinstance(value, bool)
            and (value > 0 if key == "min_final_page_fill"
                 else value >= (0 if key == "no_unexplained_gaps" else 1))
        )
    return True


_STRENGTH = {
    Enforcement.ADVISORY_STYLE: 0, Enforcement.ADVISORY_HIGH_RISK: 1, Enforcement.BINDING: 2,
}
_FORCE: dict[Enforcement, Force] = {
    Enforcement.BINDING: "strict",
    Enforcement.ADVISORY_HIGH_RISK: "soft",
    Enforcement.ADVISORY_STYLE: "soft",
}

#: An undecided rule about somebody else's document, or a line no reading
#: judged (step 1). derive._surfaced writes the first as value "third_party"
#: or "unjudged"; rule_sinks.to_notes writes the id tail "-third_par".
_DISCARDED_VALUES = frozenset({"third_party", "unjudged"})
_DISCARDED_TAILS = ("-third_par", "-unjudged")
_LINE = re.compile(r"^PAGE-(\d+)-")


def _line(rule: ConstraintRule) -> str | None:
    match = _LINE.match(rule.rule_id)
    return match[1] if match else None


def _is_discarded(rule: ConstraintRule) -> bool:
    return rule.key == "undecided" and (
        rule.value in _DISCARDED_VALUES or rule.rule_id.endswith(_DISCARDED_TAILS)
    )


def _strongest(group: Iterable[Contribution]) -> Enforcement:
    # Load-bearing for the PII boundary, not tidiness: derived page rules are
    # all ADVISORY and the Europass pre-render gate reads BINDING rules only,
    # so a merge that let the winner's own (soft) force stand would let a page
    # sentence lower a BINDING date_of_issue_required and unblock europa.eu.
    return max((c.rule.enforcement for c in group), key=_STRENGTH.__getitem__)


def _item(
    supplier: Contribution, value: object, group: Sequence[Contribution], *, conflict: str = ""
) -> Requirement:
    """The merged item: `supplier`'s rule, carrying the merged value and the
    strongest force of every rule it came from (step 7)."""
    enforcement = _strongest(group)
    rule = supplier.rule.model_copy(update={"value": value, "enforcement": enforcement})
    return Requirement(
        key=rule.key, value=value, document=supplier.document, origin=supplier.origin,
        force=_FORCE[enforcement], rule=rule,
        contributors=(rule.rule_id, *(c.rule.rule_id for c in group if c is not supplier)),
        sentence=rule.rule_text, source_url=rule.source_url, conflict=conflict,
    )


def _from_rule(
    c: Contribution, rule: ConstraintRule, *, force: Force, key: str | None = None, **extra: Any
) -> Requirement:
    """One contribution as one item carrying its own rule (`_info`, the ask)."""
    return Requirement(
        key=key or rule.key, document=c.document, origin=c.origin, force=force, rule=rule,
        contributors=(rule.rule_id,), sentence=rule.rule_text, source_url=rule.source_url,
        **extra,
    )


def _info(c: Contribution) -> Requirement:
    """A for-information item: shown, never refusing (spec §6.4 table).

    Caps force at ADVISORY_HIGH_RISK on purpose, so it must never receive a
    content-only key's winning rule: that would hide a BINDING rule from
    render._blocked_by_content_only_rules (see the note on MERGE).
    """
    enforcement = min(c.rule.enforcement, Enforcement.ADVISORY_HIGH_RISK, key=_STRENGTH.__getitem__)
    rule = c.rule.model_copy(update={"enforcement": enforcement})
    return _from_rule(c, rule, force="info", value=rule.value)


def _from_undecided(c: Contribution) -> Contribution | Requirement:
    """Step 2: an unclear sentence, by what its saved readings are about."""
    readings = c.rule.readings
    if readings is None:
        # Written before readings were saved, or about the format, a directive
        # or a condition: for information until `manage.py rederive_rules`.
        return _info(c)
    if readings.key in ASK_KEYS:
        return _from_rule(c, c.rule, force="soft", key=readings.key, ask=True)
    if readings.key in STRICTER_READING_KEYS:
        fitting = [value for value in readings.values if _fits(readings.key, value)]
        if not fitting:
            return _info(c)
        value = _COMBINE[MERGE[readings.key]](fitting)
        rule = c.rule.model_copy(update={"key": readings.key, "value": value, "readings": None})
        return Contribution(rule=rule, origin=c.origin, document=c.document, rank=c.rank)
    return _info(c)


def _merge_key(group: list[Contribution]) -> list[Requirement]:
    """Steps 3, 4 and 7 for one (document, key)."""
    theirs = sorted(
        (c for c in group if c.origin != "ours"), key=lambda c: THEIRS.index(c.origin)
    )
    if not theirs:
        # Among our own rules today's scope order stands: the more specific
        # wins, and within one scope the last in rule_id order.
        winner = max(enumerate(group), key=lambda pair: (pair[1].rank, pair[0]))[1]
        return [_item(winner, winner.rule.value, group)]
    key = theirs[0].rule.key
    row = MERGE[key]
    if row == "first":
        # The first stated by theirs applies; every later one is for information.
        first, *rest = theirs
        # The winner carries every contributor's force, losers included (step 7).
        return [_item(first, first.rule.value, group), *(_info(c) for c in rest)]
    if row == "all_kept":
        return [_item(c, c.rule.value, [c]) for c in (theirs or group)]
    # A value of the wrong type cannot be compared, and a merge that raised
    # here failed every render of the programme (final review I2). Each of
    # theirs then stands alone with its own force, so render reports the bad
    # one as it did before the merge existed, and a BINDING one keeps binding.
    alone = [_item(c, c.rule.value, [c]) for c in theirs]
    if not all(_fits(key, c.rule.value) for c in theirs):
        return alone
    try:
        if row == "per_section_lower":
            return _per_section_items(theirs, group)
        value = _COMBINE[row]([c.rule.value for c in theirs])
    except Irreconcilable:
        return [_item(c, c.rule.value, [c], conflict=key) for c in theirs]
    except (TypeError, ValueError, AttributeError):
        return alone
    supplier = next((c for c in theirs if c.rule.value == value), theirs[0])
    return [_item(supplier, value, group)]


def _per_section_items(theirs: list[Contribution], group: list[Contribution]) -> list[Requirement]:
    """`max_entries_per_section`, one rule per section (controller ruling I3).

    Step 7 gives a merged rule the strongest force of the rules its VALUE came
    from, and a section's value comes only from the rules naming that section.
    One rule for every section let SISGP's BINDING experience cap (R-078) make
    a page's soft "at most 3 publications" BINDING, and the pre-render gate
    refused a student with four. render._check_max_entries reads any dict, so
    several rules on the key are checked one by one. A supplier of two
    sections gets a numbered id on the second, so ids stay unique.
    """
    merged = cast(dict[str, int], _per_section_lower([c.rule.value for c in theirs]))
    items: list[Requirement] = []
    used: set[str] = set()
    for section, limit in merged.items():
        named = [c for c in group if isinstance(c.rule.value, dict) and section in c.rule.value]
        # _fits held for every one of theirs, so each value is a dict of ints.
        supplier = next(
            c for c in theirs if cast(dict[str, int], c.rule.value).get(section) == limit
        )
        item = _item(supplier, {section: limit}, named)
        rule = cast(ConstraintRule, item.rule)
        rule_id, n = rule.rule_id, 1
        while rule_id in used:
            n += 1
            rule_id = f"{rule.rule_id[:16]}-{n}"
        used.add(rule_id)
        if rule_id != rule.rule_id:
            item = item.model_copy(update={"rule": rule.model_copy(update={"rule_id": rule_id})})
        items.append(item)
    return items


def _directive_items(directives: Sequence[tuple[PageDirective, Origin]]) -> list[Requirement]:
    """`include` and `emphasise` all kept in theirs-first order; two `order`
    directions for one section are a conflict (step 6)."""
    ordered = sorted(directives, key=lambda pair: THEIRS.index(pair[1]))
    items: list[Requirement] = []
    seen: set[tuple[str, str, str | None]] = set()
    directions: dict[str, set[str | None]] = {}
    for directive, _origin in ordered:
        if directive.action == "order":
            directions.setdefault(directive.target, set()).add(directive.value)
    for directive, origin in ordered:
        identity = (directive.action, directive.target, directive.value)
        if identity in seen:
            continue
        seen.add(identity)
        clash = directive.action == "order" and len(directions[directive.target]) > 1
        items.append(Requirement(
            key=directive.action,
            value=[directive.target, directive.value] if directive.action == "order"
            else directive.target,
            document="cv", origin=origin, force="soft",
            sentence=directive.rule_text, source_url=directive.source_url,
            conflict=f"order:{directive.target}" if clash else "",
        ))
    return items


def _listed(name: str) -> Callable[[object], bool]:
    return lambda value: isinstance(value, list) and name in value


def _is(expected: object) -> Callable[[object], bool]:
    return lambda value: value == expected


#: Step 5: pairs of items on different keys no one CV can both satisfy.
CONTRADICTIONS: tuple[tuple[str, Callable[[object], bool], str, Callable[[object], bool]], ...] = (
    ("photo_required", _is(True), "photo_allowed", _is(False)),
    ("required_fields", _listed("photo_url"), "photo_allowed", _is(False)),
    ("required_fields", _listed("date_of_birth"), "date_of_birth_allowed", _is(False)),
    ("include", _is("personal.photo_url"), "photo_allowed", _is(False)),
    ("include", _is("personal.date_of_birth"), "date_of_birth_allowed", _is(False)),
)
#: Step 5's other shape: a floor above a cap on the same document.
FLOOR_ABOVE_CAP: tuple[tuple[str, str], ...] = (
    ("min_words", "max_words"),
    ("min_chars_excl_spaces", "max_chars_excl_spaces"),
    ("min_chars_excl_spaces", "max_chars_incl_spaces"),
)


def _contradicts(a: Requirement, b: Requirement) -> bool:
    return any(
        a.key == a_key and b.key == b_key and a_holds(a.value) and b_holds(b.value)
        for a_key, a_holds, b_key, b_holds in CONTRADICTIONS
    ) or any(
        a.key == floor and b.key == cap
        and isinstance(a.value, int | float) and isinstance(b.value, int | float)
        and a.value > b.value
        for floor, cap in FLOOR_ABOVE_CAP
    )


def _settle_cross_key(items: list[Requirement]) -> list[Requirement]:
    """Step 5. Against ours, theirs win and our item goes; between theirs,
    both sides are marked for step 6."""
    dropped: set[int] = set()
    marked: dict[int, str] = {}
    live = [i for i, item in enumerate(items) if item.force != "info" and not item.ask]
    for i in live:
        for j in live:
            a, b = items[i], items[j]
            if i == j or a.document != b.document or not _contradicts(a, b):
                continue
            if a.origin == "ours" and b.origin != "ours":
                dropped.add(i)
            elif b.origin == "ours" and a.origin != "ours":
                dropped.add(j)
            else:
                # Overlapping clashes share one name, so step 6 sees every side.
                name = marked.get(i) or marked.get(j) or f"{a.key}+{b.key}"
                for other in (marked.get(i), marked.get(j)):
                    if other and other != name:
                        marked.update({k: name for k, v in marked.items() if v == other})
                marked[i] = marked[j] = name
    return [
        items[i].model_copy(update={"conflict": marked[i]}) if i in marked else items[i]
        for i in range(len(items)) if i not in dropped
    ]


def merge(
    contributions: Sequence[Contribution],
    directives: Sequence[tuple[PageDirective, Origin]] = (),
) -> tuple[Requirement, ...]:
    """Spec §6.4 steps 1-7, in order. Step 8 is render's."""
    # Step 1: readings about someone else, or lines no reading judged, never
    # become rules -- nor does any other unclear rule on the same line of the
    # same page (review focus 5: keyed by origin, since line numbers restart).
    # The marker itself is kept as a for-information item, so the sentence is
    # still shown (owner, 2026-10-14: a skipped sentence is silent).
    elsewhere = {
        (c.origin, _line(c.rule)) for c in contributions if _is_discarded(c.rule)
    }
    items: list[Requirement] = []
    grouped: dict[tuple[str, str], list[Contribution]] = {}
    for c in contributions:
        if c.rule.key == "undecided":
            if _is_discarded(c.rule):
                items.append(_info(c))
                continue
            if (c.origin, _line(c.rule)) in elsewhere:
                continue
            settled = _from_undecided(c)
            if isinstance(settled, Requirement):
                items.append(settled)
                continue
            c = settled
        if MERGE[c.rule.key] == "info":
            items.append(_info(c))
            continue
        grouped.setdefault((c.document, c.rule.key), []).append(c)
    for group in grouped.values():
        items.extend(_merge_key(group))
    items.extend(_directive_items(directives))
    return tuple(_settle_cross_key(items))


# --- the builder (spec §6.3) --------------------------------------------------


def _catalog_contributions(
    catalog: Iterable[Any],
    *,
    program: Any,
    opportunity: Any,
    track: str,
    scope_kinds: frozenset[str] | None = None,
) -> list[Contribution]:
    contributions: list[Contribution] = []
    for row in catalog:
        if scope_kinds is not None and row.scope_kind not in scope_kinds:
            continue
        if not _scope_matches(row, program=program, opportunity=opportunity, track=track):
            continue
        rule = ConstraintRule.model_validate({
            "rule_id": row.rule_id, "key": row.key, "value": row.value,
            "enforcement": row.enforcement, "rule_text": row.rule_text,
            "source_url": row.source_url, "scope": row.scope_kind,
        })
        contributions.append(Contribution(
            rule=rule, origin=_ORIGIN_BY_SCOPE[row.scope_kind],
            rank=_SCOPE_ORDER.index(row.scope_kind),
        ))
    return contributions


def _format_item(
    program: Any, opportunity: Any, together: Sequence[Any] = ()
) -> list[Requirement]:
    """The CV format, never merged by strictness: the funder's, else a
    together award's, else the programme's (render.select_render_variant's
    order; the country's tabular layout is ours and stays render's)."""
    funder = next(
        (
            text
            for candidate in (opportunity, *together)
            if (text := str(getattr(candidate, "cv_format_requirement", "") or ""))
        ),
        "",
    )
    own = str(getattr(program, "cv_format_requirement", "") or "")
    if funder:
        origin: Origin = "scholarship"
        value, url = funder, ""
    elif own:
        origin, value = "programme", own
        url = str(getattr(program, "cv_format_source_url", "") or "")
    else:
        return []
    return [Requirement(
        key="cv_format", value=value, document="cv", origin=origin,
        force="info" if value == "any" else "strict", source_url=url,
    )]


def _letter_parts(
    shape: LetterShape, document_language: str
) -> tuple[list[Contribution], list[Requirement]]:
    """The letter's lengths as contributions (they merge by the table) and its
    other stated fields, written requirements and student actions as items."""
    from .letter_shape import constraints_from_shape

    contributions = [
        Contribution(rule=rule, origin="programme", document="letter")
        for rule in constraints_from_shape(shape, document_language=document_language)
    ]
    items: list[Requirement] = []
    for name in LETTER_FIELD_KEYS:
        if not shape.is_stated(name):
            continue
        source = shape.sources.get(name, {})
        items.append(Requirement(
            key=name, value=getattr(shape, name), document="letter", origin="programme",
            force="strict", sentence=_quote(source.get("text", "")),
            source_url=source.get("source_url", ""),
        ))
    cited: tuple[tuple[str, tuple[dict[str, str], ...], Force], ...] = (
        ("written_requirement", shape.written_requirements, "soft"),
        ("student_action", shape.student_actions, "info"),
    )
    for key, sentences, force in cited:
        items.extend(
            Requirement(
                key=key, document="letter", origin="programme", force=force,
                sentence=_quote(entry.get("text", "")),
                source_url=entry.get("source_url", ""),
            )
            for entry in sentences
        )
    return contributions, items


def build_requirements(
    program: Any,
    opportunity: Any = None,
    *,
    together: Sequence[Any] = (),
    catalog: Iterable[Any] = (),
    track: str = "",
    style_rules: Sequence[ConstraintRule] = (),
    letter_shape: LetterShape | None = None,
    document_language: str = "en",
    competencies: Sequence[str] = (),
) -> RequirementList:
    """One application's requirement list, from what the caller loaded (§6.3).

    `catalog` is every CatalogRule row in rule_id order -- the merge keeps the
    last same-scope rule, so the order is load-bearing. `together` is every
    scholarship applied for in this same application (routes
    CONSIDERED_WITH_ADMISSION / JOINT_SELECTION): it never gets a card of its
    own, so only its FUNDER-scoped catalog rows join the programme's list --
    its UNIVERSAL/TRACK/COUNTRY/INSTITUTION rows would otherwise be added a
    second time, once for the programme's own scope match and once for the
    award's. `style_rules` are our own rules held in code
    (render._UNIVERSAL_RULES). `competencies` are the programme's COMPETENCY
    statement texts, kept for relevance only.
    Raises pydantic.ValidationError on a malformed stored rule or directive,
    as rules_from_program does: a rule we cannot parse is one we cannot keep.
    """
    catalog = tuple(catalog)
    contributions = [
        *(Contribution(rule=rule, origin="ours", rank=-1) for rule in style_rules),
        *_catalog_contributions(catalog, program=program, opportunity=opportunity, track=track),
    ]
    for award in together:
        contributions.extend(_catalog_contributions(
            catalog, program=program, opportunity=award, track=track,
            scope_kinds=frozenset({"FUNDER"}),
        ))
    directives: list[tuple[PageDirective, Origin]] = []
    if program is not None:
        contributions.extend(
            Contribution(rule=rule, origin="programme") for rule in rules_from_program(program)
        )
        directives.extend((d, "programme") for d in directives_from_program(program))
    letter_items: list[Requirement] = []
    if letter_shape is not None:
        letter_rules, letter_items = _letter_parts(letter_shape, document_language)
        contributions.extend(letter_rules)
    return RequirementList(items=(
        *merge(contributions, directives),
        *_format_item(program, opportunity, together),
        *letter_items,
        *(
            Requirement(
                key="competency", document="cv", origin="programme", force="info",
                sentence=_quote(text), relevance_only=True,
            )
            for text in competencies
        ),
    ))
