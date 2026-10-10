from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

_CONSTRAINT_KEYS = Literal[
    "max_pages",
    "max_bytes",
    #: The one FLOOR among these keys; every other is a cap. S-009 says "fill
    #: the last page or cut to the previous one" and S-022 reports that a
    #: near-empty final page reads as careless -- so a CV that spills three
    #: lines onto page 2 satisfies max_pages and still loses the reader. The
    #: value is the fraction of an average earlier page the last page must
    #: carry.
    "min_final_page_fill",
    "max_entries_per_section",
    "language",
    "required_fields",
    "prohibited_content",
    "date_of_issue_required",
    "signature_required",
    "photo_allowed",
    "date_of_birth_allowed",
    #: Months of unaccounted time the history may contain. German-route
    #: applications ask for a CV "without any omissions" (uni-assist), and
    #: DAAD treats a missing period as grounds for exclusion -- so a gap is a
    #: rule about content, not about style.
    "no_unexplained_gaps",
    #: What the institution or funder says about AI-written applications. It
    #: is reported to the human who approves the draft and NEVER blocks a
    #: render: the letter engine settled this (letter_ai_policy.py's "never a
    #: generation or approval gate") and the CV side follows it. The value is
    #: the policy class -- PROHIBITS, REQUIRES_DISCLOSURE,
    #: IMMIGRATION_PROHIBITION -- and rule_text carries the published wording.
    "ai_use_policy",
    #: Two keys that carry a QUOTE rather than a value, written only by
    #: documents.derive: `undecided` -- three readings of the page did not
    #: agree what a sentence requires; `unapplied` -- they agreed it states a
    #: CV requirement that names no field, section or key this engine has.
    #: Both are ADVISORY_HIGH_RISK and have no checker: render reports them
    #: with rule_text so the student reads the page's own words (CLAUDE.md,
    #: "Who reads a CV warning"). `value` names what was in question
    #: ("cv_format", "max_pages", "cv").
    "undecided",
    "unapplied",
    "max_words",
    "min_words",
    #: The letter's character floor, measured without spaces (letter_shape
    #: _SHAPE_TO_KEY): the stricter reading of any page's floor.
    "min_chars_excl_spaces",
    "max_chars_incl_spaces",
    "max_chars_excl_spaces",
    "font",
]

#: Every key a stored rule may carry, as a set. The corpus loader
#: (apps.research.corpus) validates labels against it, so the corpus can never
#: name a requirement the engine has no contract for.
CONSTRAINT_KEYS: frozenset[str] = frozenset(get_args(_CONSTRAINT_KEYS))


class Enforcement(StrEnum):
    BINDING = "BINDING"
    ADVISORY_HIGH_RISK = "ADVISORY_HIGH_RISK"
    ADVISORY_STYLE = "ADVISORY_STYLE"


#: Keys that hold one rule PER SENTENCE rather than one per programme.
#: resolve_rules merges programme rules by key; for these two the quote is
#: the rule, and two quotes must both reach the student.
_MULTI_KEYS = frozenset({"undecided", "unapplied"})


#: Which tier answered. The catalog's five scopes plus PROGRAMME, which is
#: the programme's own page (`Program.cv_constraints`) and sits above all of
#: them, and "" for a rule that predates the field.
_SCOPE = Literal["", "UNIVERSAL", "TRACK", "COUNTRY", "INSTITUTION", "FUNDER", "PROGRAMME"]


#: How much of a page's own sentence either store keeps. Named once because
#: three places have to agree: both models below and `_quote`, which cuts
#: to it. A quote is text a third-party page controls and a human reads in a
#: warning, so the bound stays -- what changed on 2026-09-18 is that exceeding
#: it clips rather than raising.
QUOTE_MAX_CHARS = 1_000

#: What a clipped quote ends with, so a reader can see the sentence was cut
#: rather than that the page said only this much.
_CLIPPED = " [...]"


def _quote(text: str) -> str:
    """A candidate's text, cut to what the stores accept, and marked when cut.

    A reader block is not a sentence: measured 2026-09-18 on MEMBIOMED's real
    how-to-apply page, `candidates()` returned two and the longer was 1,935
    characters -- a whole checklist in one paragraph. Both quote fields cap at
    QUOTE_MAX_CHARS, so that page raised ValidationError out of
    derive_page_rules and, because read_and_derive holds one transaction, took
    the statement write with it. Three real rules lost to a crash. Moved here
    (2026-09-26, Task 8 controller ruling C5) because rule_sinks hit the same
    crash on a 1,935-character candidate sentence: one function, used by every
    caller that stores a page's own text.

    Clipping, not splitting the block into sentences: splitting changes what
    the judge is asked about on EVERY page, which is a measured surface (the
    48-row gate, the corpus), and a splitter that works in every language the
    catalog reads is its own problem. Clipping keeps the rule, keeps the bound
    on text a third-party page controls, and says it was cut.

    Never dropping the candidate is the point: a skipped sentence is silent,
    and silence is what this whole path exists to remove.
    """
    if len(text) <= QUOTE_MAX_CHARS:
        return text
    logger.warning("quote clipped: %d characters stored of %d", QUOTE_MAX_CHARS, len(text))
    return text[: QUOTE_MAX_CHARS - len(_CLIPPED)] + _CLIPPED


class ConstraintRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1, max_length=20)
    key: _CONSTRAINT_KEYS
    value: object
    enforcement: Enforcement
    rule_text: str = Field(min_length=1, max_length=QUOTE_MAX_CHARS)
    source_url: str = Field(max_length=2048, default="")
    #: Defaulted, and it has to be: `extra="forbid"` plus rules_from_program's
    #: deliberate raise means every Program.cv_constraints row written before
    #: this field existed would fail to load without one. "" is honest about
    #: those -- it says "nobody recorded a tier", not "universal".
    scope: _SCOPE = ""


def rules_from_program(program: Any) -> tuple[ConstraintRule, ...]:
    """Validate Program.cv_constraints into rules.

    Deliberately raises on a malformed stored rule instead of skipping it: a
    constraint we cannot parse is a constraint we cannot enforce, and silently
    dropping one turns a BINDING funder rule into a rendered CV that gets the
    application rejected.
    """
    return tuple(ConstraintRule.model_validate(item) for item in program.cv_constraints)


#: Fields a page may ask to be included, as "<section>.<field>". Closed and
#: pinned to CVContent by test -- a directive can only ever name a field the
#: document has. Identity fields (full_name, email) are deliberately absent:
#: they are never optional, so "include" is meaningless for them.
#:
#: They live HERE, beside the validator that reads the stored row, rather than
#: in derive.py beside the one that writes it: a target reaches the generation
#: prompt as a field name, so "the list the writer chose from" and "the list
#: the reader checks against" must be one object, not two that can drift.
_INCLUDE_TARGETS: tuple[str, ...] = (
    "education.grade_native",
    "education.grade_scale",
    "education.ects_credits",
    "education.thesis_title",
    "education.class_rank",
    "education.degree_english",
    "education.institution_english",
    "experience.supervisor",
    # A programme that asks for these can now be asked back. R-061 is BINDING
    # and says it in as many words -- Europubhealth+: "per experience, city +
    # country; no abbreviations - full names of institutions, universities,
    # projects" -- and before these three entries no directive could carry it,
    # so gaps.programme_required never asked and the CV shipped without a
    # location that a funder requires. Extraction cannot close this on its own:
    # ingestion is forbidden to supply a location it knows from world knowledge
    # ("EPFL is in Lausanne" is not something the document said), so the only
    # lawful source is the student answering.
    "experience.project",
    "experience.city",
    "experience.country",
    "research.supervisor",
    "personal.date_of_birth",
    "personal.citizenship",
    "personal.sex",
    "personal.phone",
    "personal.photo_url",
    "personal.orcid",
)
_SECTIONS: tuple[str, ...] = (
    "education", "experience", "research", "publications", "awards", "skills", "languages",
    "references",
)

#: `order` alone may name the whole document. A sentence that orders the CV
#: names no section -- DAAD EPOS, verbatim: "A curriculum vitae in reverse
#: chronological order." -- and forcing it onto one was an arbitrary choice.
#: `cv` means every dated section. `emphasise` keeps _SECTIONS: moving "the
#: whole CV" to the front of itself means nothing.
_ORDER_TARGETS: tuple[str, ...] = _SECTIONS + ("cv",)
#: The directions an `order` directive may take -- PageDirective.value's Literal.
_ORDER_DIRECTIONS: tuple[str, ...] = ("chronological", "reverse_chronological")


def check_directive_shape(action: str, target: str | None, value: str | None) -> None:
    """The shape a CV directive must have, shared by derive.Directive (the
    write side) and PageDirective (the read side) so the two validators can
    never drift apart."""
    if action == "include":
        if target not in _INCLUDE_TARGETS or value is not None:
            raise ValueError("include needs a field target and no value")
    elif action == "order":
        if target not in _ORDER_TARGETS or value not in _ORDER_DIRECTIONS:
            raise ValueError("order needs a section-or-cv target and a direction")
    elif action == "emphasise":
        if target not in _SECTIONS or value is not None:
            raise ValueError("emphasise needs a section target and no value")
    elif target is not None or value is not None:
        raise ValueError(f"{action} carries neither target nor value")


class PageDirective(BaseModel):
    """A typed generation directive stored on Program.cv_directives.

    Written only by documents.derive after three readings agreed. This model
    re-validates the stored row against the same closed lists, so a malformed
    one fails on read, as a malformed rule does.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["include", "order", "emphasise"]
    target: str = Field(min_length=1, max_length=60)
    value: Literal["chronological", "reverse_chronological"] | None = None
    rule_text: str = Field(min_length=1, max_length=QUOTE_MAX_CHARS)
    source_url: str = Field(max_length=2048, default="")

    @model_validator(mode="after")
    def _shape(self) -> PageDirective:
        """The same shape derive.Directive._shape enforces on the way in."""
        check_directive_shape(self.action, self.target, self.value)
        return self


def directives_from_program(program: Any) -> tuple[PageDirective, ...]:
    """Validate Program.cv_directives into directives, like rules_from_program."""
    return tuple(PageDirective.model_validate(item) for item in program.cv_directives)


#: Least specific first. A later scope's rule replaces an earlier one for the
#: same key. This is specificity, not strictness: DAAD's 3 pages beat the
#: taught default of 2, because a funder's own published rule is the operative
#: one, not the tightest one available.
#: INSTITUTION sits between COUNTRY and FUNDER: a university's own published
#: rule is more specific than its country's convention and less specific than
#: the funder whose form the applicant is filling. It exists because the one
#: published rule that names the CV outright -- Cambridge's AI prohibition
#: (L-041) -- is a university's, and there was no scope that could hold it.
_SCOPE_ORDER = ("UNIVERSAL", "TRACK", "COUNTRY", "INSTITUTION", "FUNDER")


def _scope_matches(rule: Any, *, program: Any, opportunity: Any, track: str) -> bool:
    if rule.scope_kind == "UNIVERSAL":
        return True
    if rule.scope_kind == "TRACK":
        return track in rule.scope_values
    if rule.scope_kind == "COUNTRY":
        return program is not None and program.country_code in rule.scope_values
    if rule.scope_kind == "INSTITUTION":
        # Institution.canonical_key, which discovery builds deterministically
        # as "<country>:<name>" (research/discovery.py::catalog_key), so a
        # seeded value matches once that institution is in the catalog and
        # matches nothing before it is.
        institution = getattr(program, "institution", None)
        return institution is not None and institution.canonical_key in rule.scope_values
    if rule.scope_kind == "FUNDER":
        return opportunity is not None and opportunity.canonical_key in rule.scope_values
    # Raise, don't skip: same reasoning as rules_from_program above -- a scope
    # kind we don't recognise is a rule we can't apply, and silently treating
    # it as "matches nobody" would let a whole new scope of researched rules
    # reach no rendered CV without any exception, failing test, or log.
    raise ValueError(f"unrecognised CatalogRule.scope_kind {rule.scope_kind!r}")


def resolve_track(program: Any, content: Any) -> str:
    """Which TRACK-scoped rules apply to this application.

    The programme decides. It used to be inferred from ``bool(content.research)``,
    which meant a classification made while ingesting a CV silently chose the
    page limit: an applicant with four research posts in academic groups
    resolved 3 pages when one was filed under `research` and 2 when all four
    were filed under `experience`. Nobody made that choice and nothing showed
    it. Track is a property of the programme applied to, so that is where it
    is read from.

    A programme whose track has not been established falls back to the old
    signal rather than defaulting every research applicant to the taught
    limit. That fallback is the remaining heuristic, and it is now the only
    one -- once `academic_track` is set, how the content was bucketed cannot
    change what is enforced.
    """
    track = getattr(program, "academic_track", "") or ""
    if track:
        return str(track)
    return "research" if content.research else "taught"


def resolve_rules(program: Any, opportunity: Any, *, content: Any) -> tuple[ConstraintRule, ...]:
    """The rules that apply to one programme-and-scholarship pair.

    Rules accumulate across scopes; when two set the same key, the more
    specific scope wins. `opportunity=None` means a self-funded, direct
    application -- the funder layer is simply absent, and universal, country
    and track rules still apply.

    Track is derived the way render.py::_section_order already derives it, so
    one CV cannot be research-track for ordering and taught-track for rules.
    """
    from apps.funding.models import CatalogRule

    track = resolve_track(program, content)
    chosen: dict[str, tuple[int, ConstraintRule]] = {}
    # order_by is load-bearing, not cosmetic: the merge below keeps the last
    # rule seen at a given rank, so two same-scope rules setting the same key
    # would otherwise resolve by Postgres row order -- a render difference
    # nothing in the code or the catalog would explain.
    for row in CatalogRule.objects.order_by("rule_id"):
        if not _scope_matches(row, program=program, opportunity=opportunity, track=track):
            continue
        rank = _SCOPE_ORDER.index(row.scope_kind)
        existing = chosen.get(row.key)
        if existing is None or rank >= existing[0]:
            chosen[row.key] = (rank, ConstraintRule.model_validate({
                "rule_id": row.rule_id,
                "key": row.key,
                "value": row.value,
                "enforcement": row.enforcement,
                "rule_text": row.rule_text,
                "source_url": row.source_url,
                # The rank decides which rule wins and was then thrown away,
                # so a warning could not say whether a page limit came from
                # the funder, the country or a programme page a model read.
                "scope": row.scope_kind,
            }))
    # A programme's own rules are the most specific there are, so they win on
    # rank -- but NEVER downwards in enforcement. A BINDING rule is a funder's
    # published requirement; an advisory one is a hint, and a hint must not be
    # able to delete a requirement.
    #
    # This became load-bearing the moment cv_constraints got its first
    # automated writer (derive.py::derive_page_rules, 2026-09-12). Every
    # derived rule is ADVISORY_HIGH_RISK, and four of the seven derivable keys
    # have BINDING seeds. Without this guard, a sentence a model read off a
    # third-party programme page silently downgraded a funder's BINDING rule
    # for every tenant -- and `date_of_issue_required` is the one that bites:
    # render.py::_blocked_by_content_only_rules only inspects BINDING rules, so
    # the downgrade stopped it blocking the EUROPASS_API branch and shipped a
    # student's name, date of birth and history to europa.eu on a render that
    # had previously been refused before any egress.
    #
    # Specificity still applies everywhere it is safe: an advisory programme
    # rule on a key nothing BINDING covers is kept as before.
    for rule in rules_from_program(program) if program is not None else ():
        existing = chosen.get(rule.key)
        if (
            existing is not None
            and existing[1].enforcement == Enforcement.BINDING
            and rule.enforcement != Enforcement.BINDING
        ):
            continue
        slot = rule.rule_id if rule.key in _MULTI_KEYS else rule.key
        chosen[slot] = (len(_SCOPE_ORDER), rule)
    return tuple(rule for _rank, rule in chosen.values())
