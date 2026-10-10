"""The shape a programme's page states for the applicant's letter.

Spec §1 and §4. Nobody reviews a finished letter (owner, 2026-09-18), so the
CV path's answer to a doubtful page -- an `undecided` rule a counsellor reads
-- has no reader here. Every disagreement resolves, per field, to the shape
that cannot break what the page requires: the smaller cap, the floor kept,
FORMAL_LETTER over ESSAY, FORBIDDEN over INVITED, the larger minimum font.
The disagreement is logged for the eval gate, never surfaced at run time,
because at run time there is nobody there.

This module also owns the LENGTH ARITHMETIC -- the bound checks, the word
target and the character clamp, moved here from `letters.py` at Task 8. The
bound semantics were expressed in three places (here, `letters.py` and
`letter_render._check_letter_constraint`); four successive fix rounds on that
arithmetic each landed in the same sixty lines, so the expressions that can be
merged are merged. What stays separate is deliberate: this module states and
targets the bounds before the model call, `letter_render` measures the finished
text against them.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal

from django.db import transaction

from apps.funding.models import ApplicationPrompt, Program, update_exactly

from .constraints import ConstraintRule, Enforcement
from .letter_defaults import DefaultRow
from .letter_gates import script_of
from .prompt_resolution import _FALLBACK_LANGUAGE

logger = logging.getLogger(__name__)

DOCUMENT_REQUIRED = ("REQUIRED", "NOT_REQUIRED", "UNSTATED")
FORMS = ("ESSAY", "FORMAL_LETTER", "PORTAL_FORM")
NAMING = ("REQUIRED", "INVITED", "FORBIDDEN", "UNSTATED")
FILE_BUNDLES = ("SEPARATE", "WITH_CV", "SINGLE_PDF_ALL")

#: Letters, digits, spaces, apostrophes and hyphens only -- every real font
#: name ("Times New Roman", "Liberation Sans", "O'Malley Serif") fits inside
#: it, and none of ";{}()/:" that would need to reach render.py's CSS to do
#: anything hostile does. font_family is the one LetterVerdict field that is
#: not a closed Literal (a page may legitimately name any font), so this is
#: the only place fabricated CSS injection can be stopped -- Django's
#: autoescaping does not neutralise ';' or '{' inside a CSS value.
_SAFE_FONT_FAMILY = re.compile(r"^[A-Za-z0-9 '\-]{1,60}$")


def _naming_decision(votes: list[str], n: int) -> str:
    """The naming verdict a vote LIST currently implies.

    FORBIDDEN always wins; REQUIRED needs unanimity across at least `n`
    votes; one vote either way is enough for INVITED. Shared between
    `decide_letter_shape`'s incremental source tracking (called after every
    vote, to see whether the ACCEPTED value just changed) and the final
    return value, so the two can never disagree with each other -- and, since
    2026-09-26, with the grammar's projection (rule_sinks.to_letter_shape).
    """
    if "forbidden" in votes:
        return "FORBIDDEN"
    if votes and len(votes) >= n and all(v == "required" for v in votes):
        return "REQUIRED"
    if "invited" in votes or "required" in votes:
        return "INVITED"
    return "UNSTATED"


def _form_decision(forms: set[str], portal_unanimous: bool) -> str:
    """Same sharing rationale as `_naming_decision`, for `form`.

    FORMAL_LETTER if any reading anywhere says letter -- it keeps the prose,
    which is the safer side. PORTAL_FORM only where every reading on one
    line said so, because a wrongly assumed form drops the letter's prose
    entirely. The grammar's projection passes True only when `portal_form` is
    the ONLY form any sentence on the page states.

    Takes the grammar's lowercase values and returns LetterShape's uppercase
    ones, like `_naming_decision`.
    """
    if "formal_letter" in forms:
        return "FORMAL_LETTER"
    if portal_unanimous:
        return "PORTAL_FORM"
    if "portal_form" in forms:
        return "FORMAL_LETTER"
    return "ESSAY"


@dataclass(frozen=True)
class LetterShape:
    """Fifteen typed answers and the sentence behind each one.

    A field with no entry in `sources` was not set by the page: it is a
    default, and the requirements pane says so (spec §1, last paragraph).
    """

    document_required: str = "UNSTATED"
    min_words: int | None = None
    max_words: int | None = None
    max_chars: int | None = None
    #: Measured without spaces (see _SHAPE_TO_KEY). Addendum 2026-09-26 §6.2.
    min_chars: int | None = None
    max_pages: float | None = None
    form: str = "ESSAY"
    signed_declaration: bool = False
    naming: str = "UNSTATED"
    font_family: str | None = None
    font_min_pt: int | None = None
    line_spacing: float | None = None
    margins_cm: float | None = None
    file_bundle: str = "SEPARATE"
    handwritten: bool = False
    sources: dict[str, dict[str, str]] = field(default_factory=dict)
    #: §3b path 2 -- into the generation prompt as data, judge-checked after.
    written_requirements: tuple[dict[str, str], ...] = ()
    #: §3b path 3 -- only the applicant can do these.
    student_actions: tuple[dict[str, str], ...] = ()
    #: §2, set by the same read: the programme's mode.
    track: str = ""
    portfolio_led: bool = False
    #: Addendum §6.4, the `language` operation. "" means the page did not say,
    #: and then nothing is written: the column belongs to whoever set it (the
    #: resolver, or the "en" a new row starts with). Set only with a sentence in
    #: `sources`, like every other field here.
    document_language: str = ""

    def is_stated(self, name: str) -> bool:
        return name in self.sources


def _decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@transaction.atomic
def apply_derived_shape(
    program: Program, cycle: str, shape: LetterShape, *, source_url: str,
    reads_language: bool = False,
) -> ApplicationPrompt:
    """Write a derived shape onto this programme's prompt for one cycle.

    The ladder's precedence (spec §4): a VERIFIED row beats everything, so a
    page read never touches one. Otherwise the shape is written onto the
    (programme, cycle) row -- created if the resolver has not run yet, so a
    derivation is never lost waiting for one.

    `Program.academic_track` and `portfolio_led` are written here too, from the
    same read: a blank track is left blank on purpose and resolves as `taught`
    at use, which is the safer of the two -- it never demands a named
    supervisor the student cannot supply.

    `reads_language`, keyword-only, defaults False: only a caller whose reader
    actually reads the letter's language (the grammar path) may reset
    `document_language` when a re-read stops stating one -- the frontier path
    (derive.py's `decide_letter_shape`) never sets the field at all, so
    without this guard its every re-read would silently wipe out a language
    the grammar path had written (fix round 2, finding 4b).
    """
    verified = ApplicationPrompt.objects.filter(
        programme=program, cycle=cycle, source=ApplicationPrompt.Source.VERIFIED
    ).first()
    if verified is not None:
        return verified
    fields = {
        "letter_document_required": shape.document_required,
        "letter_min_words": shape.min_words,
        "letter_max_words": shape.max_words,
        "letter_max_chars": shape.max_chars,
        "letter_min_chars": shape.min_chars,
        "letter_max_pages": _decimal(shape.max_pages),
        "letter_form": shape.form,
        "letter_signed_declaration": shape.signed_declaration,
        "letter_naming": shape.naming,
        "letter_font_family": shape.font_family or "",
        "letter_font_min_pt": shape.font_min_pt,
        "letter_line_spacing": _decimal(shape.line_spacing),
        "letter_margins_cm": _decimal(shape.margins_cm),
        "letter_file_bundle": shape.file_bundle,
        "letter_handwritten": shape.handwritten,
        "letter_shape_sources": shape.sources,
        "letter_written_requirements": list(shape.written_requirements),
        "letter_student_actions": list(shape.student_actions),
    }
    if shape.document_language:
        # The page stated the letter's language. Unstated leaves the column
        # alone: a page that says nothing about language has not said "English".
        fields["document_language"] = shape.document_language
    prompt = ApplicationPrompt.objects.filter(programme=program, cycle=cycle).first()
    if prompt is None:
        prompt = ApplicationPrompt.objects.create(
            programme=program, cycle=cycle, source_url=source_url, confidence=0.0,
            source=ApplicationPrompt.Source.EXTRACTED,
            funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
            structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
            **{"document_language": "en", **fields},
        )
    else:
        if prompt.source == ApplicationPrompt.Source.VERIFIED:
            # Re-checked on the row we are about to write, not only on the earlier
            # filtered read: a human verification committing between the two would
            # otherwise be overwritten by an automated derivation.
            return prompt
        if (
            reads_language
            and not shape.document_language
            and "document_language" in prompt.letter_shape_sources
        ):
            # Fix round 2, finding 4: the previous read stated a language and
            # this one does not. Leaving the column alone would keep
            # check_language_mismatch enforcing a language the page no longer
            # states, with no pane row left to say why -- reset it rather than
            # let stale enforcement outlive the sentence that justified it.
            # The reset value is _FALLBACK_LANGUAGE ("en"), not "": ""
            # is a permanent LANGUAGE_MISMATCH against any English letter
            # (content.language="en" != "") and LetterContent(language="")
            # raises ValidationError (min_length=2) the moment one is built --
            # a page stating no language must read exactly like a page that
            # never stated one, which is what a brand-new row starts as.
            # Gated on reads_language: the frontier path never sets this
            # field, so an unguarded reset would wipe a language the grammar
            # path wrote on every frontier-path re-read of the same prompt.
            fields["document_language"] = _FALLBACK_LANGUAGE
        for name, value in fields.items():
            setattr(prompt, name, value)
        prompt.save(update_fields=list(fields))
    changed: dict[str, object] = {}
    if shape.track:
        changed["academic_track"] = shape.track
    if shape.portfolio_led:
        changed["portfolio_led"] = True
    if changed:
        # funding_program carries RLS (runtime_engine_write only), so a write
        # under any other role silently affects zero rows -- the count is
        # checked, not assumed, per CLAUDE.md's RLS section.
        update_exactly(
            Program.objects.filter(id=program.id),
            error=(
                "catalog write affected no rows -- run this under DATABASE_ROLE=runtime_engine "
                "or DATABASE_ROLE=migration; no other role may update funding_program"
            ),
            **changed,
        )
    return prompt


def shape_from_prompt(prompt: ApplicationPrompt) -> LetterShape:
    """The stored shape, as the dataclass generation and render consume.

    The programme is re-read rather than taken from `prompt.programme`
    (pre-flight ruling 4): apply_derived_shape writes academic_track with a
    queryset update(), which never refreshes an already-loaded related
    instance, so the cached one would hand back a stale track.
    """
    programme = Program.objects.get(id=prompt.programme_id)
    return LetterShape(
        document_required=prompt.letter_document_required,
        min_words=prompt.letter_min_words,
        max_words=prompt.letter_max_words,
        max_chars=prompt.letter_max_chars,
        min_chars=prompt.letter_min_chars,
        max_pages=float(prompt.letter_max_pages) if prompt.letter_max_pages else None,
        form=prompt.letter_form,
        signed_declaration=prompt.letter_signed_declaration,
        naming=prompt.letter_naming,
        font_family=prompt.letter_font_family or None,
        font_min_pt=prompt.letter_font_min_pt,
        line_spacing=float(prompt.letter_line_spacing) if prompt.letter_line_spacing else None,
        margins_cm=float(prompt.letter_margins_cm) if prompt.letter_margins_cm else None,
        file_bundle=prompt.letter_file_bundle,
        handwritten=prompt.letter_handwritten,
        sources=dict(prompt.letter_shape_sources),
        written_requirements=tuple(prompt.letter_written_requirements),
        student_actions=tuple(prompt.letter_student_actions),
        track=programme.academic_track,
        portfolio_led=programme.portfolio_led,
        # letter_shape_sources decides because it is the one record of what the
        # page said: a resolver's "en" is a default, and a default that
        # round-tripped into the shape would read as stated.
        document_language=(
            prompt.document_language
            if "document_language" in prompt.letter_shape_sources else ""
        ),
    )


class NotGeneratable(ValueError):
    """Raised before any model call -- fails closed to the counselor with no generation."""


#: Two constants because refusing and aiming are different jobs. REFUSING must
#: be certain, so it uses a figure below any real prose: four characters per word
#: including the space, where English runs about six. AIMING wants the realistic
#: figure, because a target derived from the conservative one still overruns the
#: cap it was supposed to respect.
#:
#: Both are Latin-script arithmetic and neither is applied to a non-Latin script.
#: `letter-shape-terms.csv` gives zh/ja/ko an entirely CHARACTER unit vocabulary
#: -- no word unit exists for the judge to pick -- and `derive.py` keeps a floor
#: if ANY single reading found one, with none of the corroboration it demands of
#: a cap. So one reading labelling 800字以上 as `words` against a corroborated
#: 2000字 cap would refuse a Japanese shape that fits easily. (Fix round 4.)
#: Measured on this engine's own English prose, 2026-09-22 (review 1's sweep):
#: 5.759 characters per word including the space. That supports the AIMING
#: figure and not the refusing one, and 4 is kept anyway -- with the cost now
#: stated rather than implied. Every shape with
#: `max_chars/5.76 < min_words <= max_chars/4` is satisfiable-looking, passes
#: the refusal check, and is then blocked after the model call (at
#: max_chars=2000 that is a floor of 348 to 500 words). Moving the constant up
#: would refuse shapes a shorter-worded letter could satisfy, which is the more
#: expensive error, so the band is accepted and named.
_MIN_CHARS_PER_WORD = 4
_TYPICAL_CHARS_PER_WORD = 6

#: Non-space characters in one word of this engine's own prose: 5.759 measured
#: with the space (2026-09-22, above), so 4.76 without it. Used only to AIM at a
#: character floor; the word count is rounded UP, and the floor's own 15% of
#: headroom in target_word_count sits on top.
_NONSPACE_CHARS_PER_WORD = 4.76

#: Words to a page, and there is no single number: it depends on the template
#: AND on how long the words are. Four measurements through the real renderer,
#: 2026-09-22 -- at 5.762 characters per word (this engine's own measured
#: prose) a page holds 616 in `letter_continuous.html` and 499 in
#: `letter_formal.html`, whose head and foot cost it a sixth of the page; at
#: roughly 5 characters per word the same templates hold 701 and 535. The
#: first round of this task used 717/645, measured against a formal template
#: that gained its sender block in the same commit, and aiming at 600 under a
#: one-page cap rendered two pages -- the very defect it was fixing.
#:
#: So: AIMING takes the shorter ceiling of each template, with margin, because
#: an overshoot is a block paid for after the model call and an undershoot is
#: a shorter letter. REFUSING takes one above every ceiling measured, because
#: a refusal must be certain. The band between the aim and the refusal is
#: real: a floor of 617-720 words under a one-page cap is not refused and can
#: still block. It is narrower than the 800 it replaces, which was above every
#: ceiling and therefore never fired at all.
_WORDS_PER_PAGE_AIM = {"FORMAL_LETTER": 450}
_WORDS_PER_PAGE_AIM_DEFAULT = 550
#: Refusing splits per form too. The aim did and the refusal did not, so a
#: 700-word floor under a one-page FORMAL cap -- impossible on a template
#: measured at 499-550 words a page -- was not refused and was then blocked
#: after the model call (third probe). Each figure is above every ceiling
#: measured for its own template.
_WORDS_PER_PAGE_MAX = {"FORMAL_LETTER": 580}
_WORDS_PER_PAGE_MAX_DEFAULT = 720


def counts_characters(document_language: str) -> bool:
    """A script whose pages state lengths in characters, never in words.

    One reading of the language, shared with `letter_gates.script_of`, so an
    exemption here and the script check there can never disagree about what
    "ja-JP" is.
    """
    return script_of(document_language) is not None


def _effective_pages(shape: LetterShape) -> int:
    """The page cap as the checker applies it.

    `render._check_max_pages` compares an integer page count against
    `int(rule.value)`, so a stated 1.5 pages IS one page. Aiming at 1.5 x the
    per-page figure while the check floors to 1 blocked every letter under any
    cap between 1 and 2, whatever its length (re-review). Floor once, here.
    """
    return int(shape.max_pages or 0)


def _implied_word_floor(min_chars: int | None, document_language: str) -> int:
    """The word floor a character floor implies -- the SAME conversion
    ``target_word_count`` applies when aiming at one (fix round 1, finding 1).

    Without this, a character-only floor (``shape.min_words`` left ``None``)
    was invisible to the words-vs-words and words-vs-pages checks below: they
    read ``shape.min_words`` alone, so ``min_chars=2800`` next to
    ``max_words=400`` -- a floor of about 589 words that a 400-word cap
    cannot hold -- passed validation and was blocked only after the model
    call. 0 when there is nothing to imply: no floor stated, or a script
    whose pages are measured in characters, where no word bound applies.
    """
    if not min_chars or counts_characters(document_language):
        return 0
    return math.ceil(min_chars / _NONSPACE_CHARS_PER_WORD)


def validate_shape_bounds(shape: LetterShape, document_language: str = "en") -> None:
    """A length bound this engine cannot satisfy is a refusal, not instructions.

    Fix round 1, finding 3 covered a stated floor above a stated cap. Fix round
    3 extends the same ruling -- both directions of a contradiction end in a
    block, so refuse early rather than spend a model call on a letter
    ``letter_render`` will throw away -- to the two cases it left open:

    * ``0`` is a legal ``PositiveIntegerField`` value, and the old guard's
      truthiness read it as "no bound stated", skipping every check.
    * the word and character bounds were never compared, so a 900-word floor
      against a 2,000-character cap emitted both sentences and refused nothing.

    Called both here (so a direct unit test on ``_shape_instructions`` sees the
    same guard) and early in ``generate_letter`` (so the failure is caught
    before any rate-limit budget is spent, matching the naming check above it).
    """
    if shape.max_words == 0:
        raise NotGeneratable("letter shape unsatisfiable: stated cap of 0 words")
    if shape.max_chars == 0:
        raise NotGeneratable("letter shape unsatisfiable: stated cap of 0 characters")
    if shape.max_pages is not None and shape.max_pages < 1:
        # Task 7 residual (e), widened by review 1. The same defect as the two
        # above, on the one bound no prompt sentence mentions: nothing
        # instructs the model about pages, so this would have reached
        # letter_render as a rule no letter can satisfy, after the model call
        # was paid for. ANY value below 1 is that, not just 0 --
        # `_check_max_pages` compares an integer page count, so "half a page"
        # (a stateable rule, and `letter_max_pages` stores one decimal place)
        # blocks every letter that exists.
        raise NotGeneratable(
            f"letter shape unsatisfiable: stated cap of {shape.max_pages} pages"
        )
    # fix round 1, finding 1: a character-only floor is folded in here so it
    # reaches the SAME words-vs-words and words-vs-pages checks a word floor
    # gets, rather than a raw shape.min_words that stays None when only
    # min_chars is stated.
    implied_min_words = _implied_word_floor(shape.min_chars, document_language)
    effective_min_words = max(shape.min_words or 0, implied_min_words) or None
    if shape.max_words and effective_min_words and effective_min_words > shape.max_words:
        raise NotGeneratable(
            f"letter shape unsatisfiable: floor of {effective_min_words} words exceeds "
            f"cap of {shape.max_words} words"
        )
    if shape.min_chars and shape.max_chars and shape.min_chars > shape.max_chars:
        # min_chars is counted without spaces and max_chars with them, so a
        # floor above the cap is unsatisfiable outright -- never merely tight.
        raise NotGeneratable(
            f"letter shape unsatisfiable: floor of {shape.min_chars} characters exceeds "
            f"cap of {shape.max_chars} characters"
        )
    if shape.min_chars and shape.max_chars:
        # min_chars > max_chars above catches the case where the floor
        # (without spaces) already exceeds the cap (with spaces) on its own
        # numbers. This catches the tighter, commoner case: the floor is
        # numerically under the cap, but the WITH-SPACES text it takes to
        # clear it is not -- min_chars=2800 next to max_chars=3000 passed
        # before this, although 2800 non-space characters takes about 3,529
        # characters with spaces to write.
        needed_with_spaces = shape.min_chars * (_TYPICAL_CHARS_PER_WORD / _NONSPACE_CHARS_PER_WORD)
        if needed_with_spaces > shape.max_chars:
            raise NotGeneratable(
                f"letter shape unsatisfiable: a floor of {shape.min_chars} characters "
                f"(without spaces) takes about {round(needed_with_spaces)} characters with "
                f"spaces to write, above the stated cap of {shape.max_chars} characters"
            )
    if effective_min_words and shape.max_pages and not counts_characters(document_language):
        # The third cross-check, and the one nobody wrote: words against pages.
        # A 800-word floor under a one-page cap has no satisfying letter, and
        # before this every candidate length was generated and then blocked by
        # one bound or the other. A character-only floor reaches this check
        # too now, through effective_min_words -- min_chars vs max_pages was
        # never checked at all before fix round 1.
        per_page = _WORDS_PER_PAGE_MAX.get(shape.form, _WORDS_PER_PAGE_MAX_DEFAULT)
        holds = _effective_pages(shape) * per_page
        if effective_min_words > holds:
            raise NotGeneratable(
                f"letter shape unsatisfiable: a floor of {effective_min_words} words does not "
                f"fit the stated cap of {shape.max_pages} pages, which holds at most {holds}"
            )
    if shape.min_words and shape.max_chars and not counts_characters(document_language):
        needed = shape.min_words * _MIN_CHARS_PER_WORD
        if needed > shape.max_chars:
            raise NotGeneratable(
                f"letter shape unsatisfiable: a floor of {shape.min_words} words needs at "
                f"least {needed} characters, above the stated cap of {shape.max_chars}"
            )


def target_word_count(
    shape: LetterShape, row: DefaultRow, document_language: str = "en"
) -> int:
    """The target word count, always inside whatever range the page states.

    Fix round 1, finding 3. With a cap: aim at 85% of it -- a letter written
    TO the cap overruns it once hygiene and the header block are added --
    but never below a stated floor and never above the cap. With only a
    floor: aim at the larger of the floor or the default row's own target
    (previously the target ignored a lone floor entirely and could undercut
    it, e.g. System D's 450-word default against a page stating only "at
    least 400 words"). With neither, the default row's own target stands.
    ``validate_shape_bounds`` has already ruled out an impossible range.

    Every branch then passes through EVERY clamp. Review 1 found fix round 4's
    character clamp reachable from two of the three branches: a shape stating
    500 words and 2,000 characters aimed at 425 words, wrote 2,444 characters
    and was blocked by its own other bound. A clamp that one branch skips is
    not a clamp, so the branches now choose a raw target and nothing else.
    """
    implied = _implied_word_floor(shape.min_chars, document_language)
    if implied:
        # A character floor is aimed at as the word floor it implies, so every
        # branch and clamp below respects it exactly as it respects min_words.
        # Without this a page stating only "at least 2,800 characters" got the
        # row's own 450 words (about 2,140 non-space characters) and was blocked
        # after the model call. Same helper validate_shape_bounds uses, so the
        # refusal and the target agree on what a character floor implies.
        shape = replace(shape, min_words=max(shape.min_words or 0, implied))
    if shape.max_words:
        target = min(max(int(shape.max_words * 0.85), shape.min_words or 0), shape.max_words)
    elif shape.min_words:
        if row.word_target > shape.min_words:
            target = row.word_target
        else:
            # The floor binds, so the row's own target would sit ON it -- and a
            # letter written TO a bound lands on the wrong side of it. 15% of
            # headroom, the mirror of the 85% below a cap and for the same
            # reason: letter_render blocks a short letter as a min_words
            # violation exactly as it blocks a long one, and nobody reviews a
            # finished letter. Only when the floor binds: where the row's
            # target already clears it, a curated default beats an arithmetic
            # one. (Fix round 2, finding 2.)
            target = int(shape.min_words * 1.15)
    else:
        target = row.word_target
    target = _held_by_characters(target, shape, document_language)
    target = _held_by_pages(target, shape, document_language)
    if target < 1:
        # "Write about 0 words." was instructed, and whatever came back was
        # blocked by the same bound that produced the 0 (review 1): a cap of
        # one word, or of fewer characters than a word takes. Refused here
        # rather than in the guard because this is where the arithmetic that
        # produces it lives, and this still runs before any model call.
        raise NotGeneratable(
            "letter shape unsatisfiable: the stated bounds leave room for 0 words"
        )
    return target


def target_characters(shape: LetterShape) -> int:
    """The character target for a script whose pages count characters.

    85% of the stated cap, the same headroom a word cap gets, and the same
    refusal at zero: `LetterShape(max_chars=1)` instructed "Write about 0
    characters." because this branch never entered `target_word_count`, where
    that refusal lives (third probe).
    """
    target = int((shape.max_chars or 0) * 0.85)
    if target < 1:
        raise NotGeneratable(
            "letter shape unsatisfiable: the stated bounds leave room for 0 characters"
        )
    return target


def _held_by_pages(target: int, shape: LetterShape, document_language: str) -> int:
    """Clamp a word target to what a stated page cap can hold.

    Per FORM, because the formal template spends a sixth of its first page on
    the sender block, date, addressee, salutation, closing and signature. A
    shape whose formalities turn out to be unavailable renders as an essay and
    is aimed low, which is the safe direction.

    Review 1: `max_pages` was a BINDING rule that nothing aimed at. A System-C
    programme's 750-word default under a stated one-page cap rendered two
    pages and was blocked -- after the model call. Never below a stated floor,
    for the same reason as the character clamp: a floor no cap can hold is
    already refused above.
    """
    if not shape.max_pages or counts_characters(document_language):
        return target
    per_page = _WORDS_PER_PAGE_AIM.get(shape.form, _WORDS_PER_PAGE_AIM_DEFAULT)
    return max(shape.min_words or 0, min(target, _effective_pages(shape) * per_page))


def _held_by_characters(target: int, shape: LetterShape, document_language: str) -> int:
    """Clamp a word target to what a stated character cap can actually hold.

    Fix round 4. validate_shape_bounds checks the STATED bounds against each
    other; nothing checked the target this module computes. A page stating only
    a character cap -- the commonest shape there is -- got the row's own target
    regardless, so 550 words were instructed against 2,000 characters and
    letter_render blocked whichever bound the model honoured. Never below a
    stated floor: a floor no cap can hold is already refused above.
    """
    if not shape.max_chars or counts_characters(document_language):
        return target
    return max(shape.min_words or 0, min(target, shape.max_chars // _TYPICAL_CHARS_PER_WORD))


#: The shape fields letter_render can measure, and the constraint key each one
#: becomes. max_chars maps to the INCLUSIVE key: every page measured in the
#: research counts spaces (M-012, M-014).
_SHAPE_TO_KEY = {
    "max_words": "max_words",
    "min_words": "min_words",
    "max_chars": "max_chars_incl_spaces",
    #: The floor is measured WITHOUT spaces: the stricter reading of any page,
    #: so the page's own convention never needs to be known.
    "min_chars": "min_chars_excl_spaces",
    "max_pages": "max_pages",
}


def constraints_from_shape(
    shape: LetterShape, *, document_language: str = "en"
) -> tuple[ConstraintRule, ...]:
    """The shape as BINDING rules, each carrying the sentence that set it.

    BINDING because nobody reviews the letter: an advisory violation here
    would be a warning with no reader, and a letter over a published cap is
    rejected by the portal that counts it.

    A bound with no `sources` entry still becomes a rule -- it is a real bound
    on the stored prompt, a human may have typed it -- but its `rule_text`
    says where it came from rather than pretending to quote a page. That
    string is what `letter_render` shows when the bound blocks a render.
    """
    rules: list[ConstraintRule] = []
    word_counted = not counts_characters(document_language)
    for name, key in _SHAPE_TO_KEY.items():
        value = getattr(shape, name)
        if value is None:
            continue
        if key in ("max_words", "min_words") and not word_counted:
            # letter_render measures a word bound with `text.split()`, which
            # returns 1 for a page of Japanese. Fix round 4 exempted this
            # script from the refusal and the target and left this function
            # out (review 1), so an 800-word floor became a BINDING rule that
            # NO Japanese letter can satisfy -- converting a free refusal into
            # a block paid for after the model call. The bound is not dropped
            # quietly: it is unmeasurable in this script and says so.
            logger.warning(
                "letter shape: %s is not measurable in %r and is not enforced",
                name,
                document_language,
            )
            continue
        source = shape.sources.get(name, {})
        rules.append(
            ConstraintRule(
                rule_id=f"SHAPE-{name[:14]}",
                key=key,  # type: ignore[arg-type]
                value=value,
                enforcement=Enforcement.BINDING,
                rule_text=source.get("text")
                or f"{name} = {value} on the stored prompt, with no page sentence recorded",
                source_url=source.get("source_url", ""),
            )
        )
    return tuple(rules)
