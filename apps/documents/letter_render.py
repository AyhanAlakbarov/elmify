from __future__ import annotations

import csv
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import cast

from django.template.loader import render_to_string
from pydantic import ValidationError

from .constraints import ConstraintRule, Enforcement
from .hygiene import normalize_text
from .letter_gates import sentence_spans
from .letter_schemas import LetterContent, LetterUnit
from .letter_shape import LetterShape
from .render import (
    ContentHygieneFailed,
    PreflightBlocked,
    RenderedArtifact,
    _check_max_bytes,
    _check_max_pages,
    _clean,
    render_html_to_artifact,
)

logger = logging.getLogger(__name__)

_TEMPLATE_BY_VARIANT = {
    "LETTER_PDF": "documents/letter_continuous.html",
    "LETTER_FORMAL": "documents/letter_formal.html",
    "TWO_SECTION_FORM": "documents/letter_two_section.html",
}

_STRUCTURE_TO_VARIANT = {
    "SHORT_ANSWER_SET": "FIELD_MAPPED",
    "CONTINUOUS_LETTER": "LETTER_PDF",
    "TWO_STATEMENTS": "LETTER_PDF",
    "PRESCRIBED_RESEARCH_FORM": "TWO_SECTION_FORM",
}


@dataclass(frozen=True)
class LetterConstraintViolation:
    rule: ConstraintRule
    detail: str


#: The font families this system ships, and the generic class each falls back
#: to. Measured from the image's own font packages: `fonts-dejavu-core` (the
#: templates' default) and `fonts-liberation`, whose three faces are the
#: licensed metric-compatible stand-ins for Times New Roman, Arial and Courier
#: New -- Debian's fontconfig maps those names onto them, so a page stating
#: one renders at the metrics it published.
#:
#: The Microsoft originals are deliberately NOT shipped: they are Monotype's,
#: and the only Debian route downloads them under an EULA forbidding
#: redistribution of the extracted files, which is what embedding a font in
#: every PDF we produce does. What that costs is the NAME -- the PDF records
#: `Liberation-Serif` -- and nothing else: metrics, and therefore page count,
#: are identical. Measured INSIDE THE BUILT IMAGE, 2026-09-23, 600 words at
#: 12pt: "Times New Roman" renders Liberation-Serif over 2 pages and "Arial"
#: Liberation-Sans over 2, where DejaVu Serif takes 3 for the same words. So a
#: page asking for "Times New Roman, max 2 pages" is satisfiable now and was
#: impossible before, and a substitution of DIFFERENT metrics still blocks
#: (owner decision, 2026-09-23, amending the spec's "never substitutes" to
#: "never substitutes different metrics").
#:
#: Anything not named here still blocks, and the block is the whole point:
#: fontconfig never fails, it answers. Measured in that same image, an
#: unblocked "Garamond Pro" renders as DejaVu Serif over 3 pages -- a different
#: typeface AND a page more, with the page's stated requirement unmet and
#: nothing saying so.
SHIPPED_FONTS: dict[str, str] = {
    "DejaVu Sans": "sans-serif",
    "DejaVu Serif": "serif",
    "Liberation Sans": "sans-serif",
    "Liberation Serif": "serif",
    "Liberation Mono": "monospace",
    "Arial": "sans-serif",
    "Times New Roman": "serif",
    "Courier New": "monospace",
}

#: docs/research/letter-formalities.csv, one row per language.
_FORMALITIES_CSV = Path(__file__).resolve().parents[2] / "docs/research/letter-formalities.csv"


@dataclass(frozen=True)
class Formality:
    """One language's salutation, closing and place-and-date convention.

    `reader` is who the source's letter is addressed to, and it is not
    decoration: every row here comes from an ADMISSIONS form, and System F --
    the immigration systems -- also defaults to FORMAL_LETTER. Without the
    column, an Irish study-visa letter opened "Dear members of the Admissions
    Committee," (review 3, measured through `defaults_for` across 55
    countries), when M-084 says in its own words that it is "read by the visa
    office, never the university". A caller states who reads the letter; a row
    is used only for that reader, and the default states nothing and gets no
    formalities.
    """

    language: str
    reader: str
    salutation: str
    closing: str
    place_and_date: bool
    source: str

    @property
    def complete(self) -> bool:
        """Both formulas sourced. A row missing one is not usable.

        Portuguese has a sourced closing and no sourced salutation, and
        rendered a formal letter that opened with nothing at all (review 2).
        The fallback was written per ROW; the gap is per FIELD, and half a
        formal letter is the outcome the fallback exists to avoid.
        """
        return bool(self.salutation and self.closing)


def _load_formalities() -> dict[str, Formality]:
    """Read the formalities table.

    Three languages, not five. The task plan proposed en/fr/es/pt/de rows
    whose formulas appear nowhere in the rules they cited -- the "de" row cited
    M-084, which is an Ireland study-visa rule, and M-005 is an explicit
    finding that DAAD prescribes no formalities at all. Each row here carries
    wording its own rule states verbatim, and a test checks that against
    letter-shape-rules.csv.

    French is the gap that matters: M-025 gives the salutation ("Madame,
    Monsieur,") and says a formule de politesse is obligatory, but its source
    deck -- fetched and read, 2026-09-22 -- names no closing, it links out for
    one. A French formal letter therefore renders as an essay until a sourced
    closing exists, which is the spec's own rule for a language with no row.

    Three rows, and after review 3 checked each against its primary source,
    ONE of them is usable. "Presente" was moved out of the Spanish salutation:
    UNAM's own template (fetched) puts it on the line under the recipient,
    inside the addressee block, and has no salutation -- so `es` joins `pt` as
    a row with a sourced closing and no sourced opening, and both fall back.
    What ships is English, from one Dutch university's psychology form. Read
    that as the sample it is: three institutions were standing in for three
    world languages, and the spec's section 10 already says the research is a
    sample. The rows stay in the file as the record of where each gap is.
    """
    with _FORMALITIES_CSV.open(encoding="utf-8") as handle:
        return {
            row["language"]: Formality(
                language=row["language"],
                reader=row["reader"],
                salutation=row["salutation"],
                closing=row["closing"],
                place_and_date=row["place_and_date"] == "yes",
                source=row["source"],
            )
            for row in csv.DictReader(handle)
        }


FORMALITIES = _load_formalities()


#: Who reads the letter, per `ApplicationPrompt.FunderKind`. Only one kind has
#: a reader, because only one sourced row exists and it is a UNIVERSITY
#: ADMISSIONS form: a scholarship board, a development foundation, a visa
#: office (M-084: "read by the visa office, never the university") and a
#: research supervisor are each a different reader, and none of them has a row.
#: Anything else means no formalities, which is the essay -- never a borrowed one.
def reader_for(funder_kind: str) -> str:
    return "ADMISSIONS" if funder_kind == "UNIVERSITY_ADMISSION" else ""


def renders_formal_letter(structure: str, form: str) -> bool:
    """Whether this structure and form reach `letter_formal.html`.

    Asked by `letters._shape_instructions`, which must not raise on a
    structure this module has no template for: `CONSORTIUM_SPECIFIC` and
    `VIDEO` are legal prompt structures that `generate_letter` refuses by
    name, and asking `select_letter_variant` about one was a bare KeyError
    (third probe).
    """
    return form == "FORMAL_LETTER" and _STRUCTURE_TO_VARIANT.get(structure) == "LETTER_PDF"


def formality_for(language: str, reader: str) -> Formality | None:
    """The row to render this letter's formalities from, or None.

    None means the essay template, never another language's salutation and
    never another reader's. A row that is missing either formula is None too
    (see `Formality.complete`).
    """
    # Lowercased: `check_language_mismatch` compares languages with .lower(),
    # so a model answering "EN" against a prompt saying "en" passes every gate
    # and then found no row here -- a formal letter with neither an opening
    # nor a close, which is the outcome the fallback exists to prevent
    # (re-review).
    formality = FORMALITIES.get(language.lower())
    if formality is None or not formality.complete or formality.reader != reader:
        return None
    return formality


def letter_context(
    shape: LetterShape | None,
    *,
    formality: Formality | None = None,
    addressee: str = "",
    applicant_name: str = "",
    place_and_date: str = "",
) -> dict[str, object]:
    """Everything a letter template reads besides `content`.

    The three caller strings go through `normalize_text` here, for the reason
    `hygienic_content` gives: without it "invisible characters, bidi overrides
    and mojibake reach the PDF". They are new parameters, so the letter
    hygiene pass -- which runs over `content` -- never saw them, and a right-
    to-left override in `applicant_name` printed the signature reversed
    (review 2).
    """
    return {
        "shape": shape,
        "style": _shape_style(shape),
        "formality": formality,
        "addressee": normalize_text(addressee),
        "applicant_name": normalize_text(applicant_name),
        "place_and_date": normalize_text(place_and_date),
    }


def _shape_style(shape: LetterShape | None) -> dict[str, str]:
    """The shape's typography, as CSS-ready strings.

    Coerced in Python and never interpolated as a number in the template, for
    two independent reasons, both measured (review 2):

    * Django localises a float in `{{ }}` against the ACTIVE language, so
      `margins_cm=2.5` renders `margin: 2,5cm` under a German locale. That is
      a CSS parse error, the declaration is dropped silently, and the same
      letter came out 2 pages under `en` and 1 under `de` -- which is then
      what the BINDING `max_pages` rule is measured against.
    * `LetterShape` is an ordinary dataclass and `render_letter` takes any
      instance, so the only thing keeping a CSS payload out of the `<style>`
      block was the column type on `ApplicationPrompt`. `float()`/`int()` puts
      that guard in the module that renders the CSS.
    """
    # DejaVu Sans by name, not "Helvetica": with Liberation in the image,
    # fontconfig maps Helvetica onto Liberation Sans, so the DEFAULT letter
    # would have changed typeface -- and every words-per-page figure in
    # letter_shape.py was measured on DejaVu. A default that names what it
    # gets keeps those numbers true.
    family = shape.font_family if shape is not None and shape.font_family else "DejaVu Sans"
    try:
        return {
            # Reached only after the SHIPPED_FONTS gate above, or defaulted here.
            "font_family": family,
            "generic": SHIPPED_FONTS.get(family, "sans-serif"),
            "font_pt": (
                str(int(_positive(shape.font_min_pt, "font_min_pt")))
                if shape and shape.font_min_pt
                else "11"
            ),
            "line_height": (
                str(_positive(shape.line_spacing, "line_spacing"))
                if shape and shape.line_spacing
                else "1.5"
            ),
            "margin_cm": (
                str(_positive(shape.margins_cm, "margins_cm"))
                if shape and shape.margins_cm
                else "2"
            ),
        }
    except (TypeError, ValueError) as error:
        # PreflightBlocked, not a bare ValueError: this is a render refusing
        # to render, and every other refusal on this path is that type.
        raise PreflightBlocked(f"letter shape carries a value CSS cannot take: {error}") from None


def _positive(value: object, name: str) -> float:
    """A finite, positive number, or a refusal.

    `float("nan")`, `float("inf")` and a negative point size all coerced
    happily and emitted `margin: nancm`, `line-height: inf`, `font-size: -5pt`
    -- CSS drops each one silently, which is the same failure the locale
    comment above documents: the page count the BINDING `max_pages` rule is
    measured against comes from a shape that was never applied (third probe).
    """
    number = float(cast(float, value))
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive number, not {value!r}")
    return number


def select_letter_variant(structure: str, *, form: str = "ESSAY") -> str:
    """The template for this structure, and for a formal letter its own.

    `form` only ever upgrades a continuous letter. A PORTAL_FORM structure is
    typed into someone else's boxes and a PRESCRIBED_RESEARCH_FORM has its own
    prescribed one: neither has anywhere to put a date, an addressee or a
    sign-off, so a page calling itself a letter does not change what is
    rendered there.
    """
    variant = _STRUCTURE_TO_VARIANT[structure]
    if form == "FORMAL_LETTER" and variant == "LETTER_PDF":
        return "LETTER_FORMAL"
    return variant


#: The two sections letter_two_section.html actually has. They are exactly
#: the archetypes the RESEARCH_SUPERVISOR playbook generates
#: (silent_funder.DEFAULT_ARCHETYPES_BY_FUNDER_KIND), which is what makes a
#: third archetype in a PRESCRIBED_RESEARCH_FORM a disagreement between the
#: prompt and the renderer rather than an ordinary exclusion.
_TWO_SECTION_ARCHETYPES = frozenset({"ACADEMIC_PREPARATION", "RESEARCH_PLAN"})


def _rendered_units(content: LetterContent, variant: str) -> tuple[LetterUnit, ...]:
    """The units that will actually reach the reader, per variant.

    Two render paths drop units, and the constraint check used to measure
    every unit regardless -- so a word count could pass on text the reader
    never receives, which is the wrong direction for a limit whose whole
    point is what the reader gets.
    """
    if variant == "FIELD_MAPPED":
        # Last unit per question, exactly as _render_field_mapped's dict
        # resolves it: two units answering "q1" send ONE answer to the portal,
        # and counting both blocked a letter for a length the portal never
        # receives (review 1) -- the same direction this docstring forbids.
        answered = {
            unit.answers_question: unit for unit in content.units if unit.answers_question
        }
        return tuple(answered.values())
    if variant == "TWO_SECTION_FORM":
        return tuple(unit for unit in content.units if unit.archetype in _TWO_SECTION_ARCHETYPES)
    return content.units


def _full_text(units: tuple[LetterUnit, ...]) -> str:
    return " ".join(unit.text for unit in units)


def _validated(payload: object) -> LetterContent:
    try:
        return LetterContent.model_validate(payload)
    except ValidationError as error:
        fields = ", ".join(".".join(str(part) for part in err["loc"]) for err in error.errors())
        raise ContentHygieneFailed(f"hygiene pass invalidated field(s): {fields}") from None


def _sentence_window(
    spans: list[tuple[str, int, int]], span_start: int, span_end: int
) -> tuple[int, int] | None:
    """Which sentences of ``spans`` a claim's ``[span_start, span_end)`` covers.

    Half-open overlap first (a span that already encloses one or more whole
    sentences -- the schema's contract -- selects exactly those); a span that
    overlaps nothing falls back to the sentence containing its start, which
    is what a zero-length span at a sentence boundary produces. ``None`` means
    the span locates nothing in this text at all, and the caller leaves it
    alone rather than guessing: an un-relocatable claim covers no sentence,
    so ``check_claim_coverage`` fires instead of being silently satisfied.
    """
    overlapping = [i for i, (_, s, e) in enumerate(spans) if span_start < e and span_end > s]
    containing = [i for i, (_, s, e) in enumerate(spans) if s <= span_start <= e]
    hits = overlapping or containing
    return (hits[0], hits[-1]) if hits else None


def hygienic_letter_content(content: LetterContent) -> LetterContent:
    """Clean a letter's text and re-anchor every claim span onto the cleaned
    text's enclosing sentence(s).

    render.py's generic ``hygienic_content`` cleans every string field and
    then re-validates the model as-is. That is not enough for LetterContent,
    for two reasons.

    First, cleaning is not a no-op transform for arbitrary text: removing
    even one character ahead of a claim (a stray zero-width space, a control
    character) shifts every later offset, so the untouched
    ``span_start``/``span_end`` from generation no longer bound the same text
    inside the (also-cleaned) unit text -- silently desynchronizing
    ``check_claim_coverage``'s sentence-to-claim mapping instead of raising
    anything.

    Second -- and this is what the re-anchoring has to preserve --
    ``check_claim_coverage`` asks whether a claim's span **encloses a whole
    triggering sentence** (``span_start <= start and span_end >= end``), and
    ``LetterClaim.text`` is typically a short phrase quoted out of a longer
    sentence. Re-deriving each span from where its own cleaned ``text`` sits
    therefore produced a span narrower than any sentence, and every letter
    carrying a phrase-shaped claim was blocked with ``UNDECLARED_ASSERTION``
    deterministically. Spans are re-anchored to sentence bounds, via
    ``letter_gates.sentence_spans`` so both sides split identically; the
    contract is stated on ``LetterClaim.span_start``/``span_end`` themselves.

    Nothing in ``LetterContent``'s schema relates a claim's span to its unit's
    text -- there is no cross-field validator, not even ``span_end >
    span_start`` -- so re-validation here catches only per-field problems
    (``text`` normalising to ``""``, a length or type violation). The
    span-level protection is the sentence-count check below: if cleaning
    changed how many sentences a unit has, the text was genuinely
    restructured rather than merely rewritten character for character, no
    claim can be mapped across with confidence, and this fails closed via
    ``ContentHygieneFailed``.
    """
    cleaned = _validated(_clean(content.model_dump(mode="json")))
    payload = cast(dict[str, object], cleaned.model_dump(mode="json"))
    units = cast(list[dict[str, object]], payload["units"])
    for original, unit in zip(content.units, units, strict=True):
        claims = cast(list[dict[str, object]], unit["claims"])
        if not claims:
            continue
        before = sentence_spans(original.text)
        after = sentence_spans(cast(str, unit["text"]))
        if len(before) != len(after):
            raise ContentHygieneFailed("hygiene pass invalidated field(s): units.text")
        for claim in claims:
            window = _sentence_window(
                before, int(cast(int, claim["span_start"])), int(cast(int, claim["span_end"]))
            )
            if window is None:
                continue
            first, last = window
            claim["span_start"] = after[first][1]
            claim["span_end"] = after[last][2]
    return _validated(payload)


#: Keys this function can measure from the letter's own text. Anything else
#: fails closed below rather than being silently treated as satisfied.
_TEXT_CONSTRAINT_KEYS = frozenset(
    {"max_words", "min_words", "max_chars_incl_spaces", "max_chars_excl_spaces",
     "min_chars_excl_spaces"}
)
#: Measured after rendering, by render.py's _CHECKERS, against the artefact.
_ARTIFACT_CONSTRAINT_KEYS = frozenset({"max_pages", "max_bytes"})

#: The subset of render.py's _CHECKERS registry this module can call: both
#: checkers were widened (Task 16) to take `content: object` because neither
#: reads it, so calling them with a LetterContent instead of a CVContent is
#: sound. Indexing render.py's own `_CHECKERS` dict here instead would call
#: through its declared `Callable[[ConstraintRule, CVContent, ...]]` value
#: type -- correct for the CVContent-reading checkers still in that registry,
#: but not for a LetterContent argument.
_CHECKERS: dict[str, Callable[[ConstraintRule, object, RenderedArtifact], str | None]] = {
    "max_pages": _check_max_pages,
    "max_bytes": _check_max_bytes,
}


def _check_question_limits(
    artifact: RenderedArtifact, questions: list[dict[str, object]] | None
) -> None:
    """Enforce per-question caps for SHORT_ANSWER_SET.

    Portal caps are published per question (`prompt.questions[].max_words` /
    `max_chars_incl_spaces`), not per document, so a `constraints`-level rule
    cannot express them: four 150-word answers pass a 600-word document cap
    while every one of them overruns its own box. Chevening, Gates,
    Commonwealth and Australia GS all publish caps in this shape.

    Always blocking, with no enforcement tier: these come from the funder's own
    form rather than from a ConstraintRule, and a portal that counts the limit
    truncates or rejects rather than warning.

    A question the letter never answered reads as "" and passes its cap. That
    is deliberate -- this is a ceiling, not a floor. Unanswered questions are
    Task 6's PROMPT_REQUIREMENT_UNMET gate, not this function.
    """
    mapped = artifact.field_mapped or {}
    for question in questions or ():
        question_id = str(question["id"])
        text = str(mapped.get(question_id, ""))
        max_words = question.get("max_words")
        if max_words is not None and len(text.split()) > int(cast(int, max_words)):
            raise PreflightBlocked(
                f"{question_id}: {len(text.split())} words exceeds {max_words}"
            )
        max_chars = question.get("max_chars_incl_spaces")
        if max_chars is not None and len(text) > int(cast(int, max_chars)):
            raise PreflightBlocked(f"{question_id}: {len(text)} characters exceeds {max_chars}")


def _check_letter_constraint(
    rule: ConstraintRule, *, text: str
) -> LetterConstraintViolation | None:
    word_count = len(text.split())
    if rule.key == "max_words" and word_count > int(cast(int, rule.value)):
        return LetterConstraintViolation(rule, f"{word_count} words exceeds {rule.value}")
    if rule.key == "min_words" and word_count < int(cast(int, rule.value)):
        return LetterConstraintViolation(rule, f"{word_count} words below floor {rule.value}")
    if rule.key == "max_chars_incl_spaces" and len(text) > int(cast(int, rule.value)):
        return LetterConstraintViolation(rule, f"{len(text)} characters exceeds {rule.value}")
    if rule.key == "max_chars_excl_spaces":
        # Fix round 1, finding 7: strip every whitespace character, not just
        # " " -- a newline, tab or NBSP still counted toward the cap before
        # this, undercounting a letter that should have been blocked.
        stripped_len = len(re.sub(r"\s", "", text))
        if stripped_len > int(cast(int, rule.value)):
            return LetterConstraintViolation(
                rule, f"{stripped_len} characters exceeds {rule.value}"
            )
    if rule.key == "min_chars_excl_spaces":
        stripped_len = len(re.sub(r"\s", "", text))
        if stripped_len < int(cast(int, rule.value)):
            return LetterConstraintViolation(
                rule, f"{stripped_len} characters below floor {rule.value}"
            )
    if rule.key in _TEXT_CONSTRAINT_KEYS or rule.key in _ARTIFACT_CONSTRAINT_KEYS:
        # Artifact keys are deferred, not skipped: render_letter measures them
        # against the rendered artefact via render.py's own checkers.
        return None
    # Fail closed on anything this function cannot measure, matching
    # render.py's _CHECKERS branch: "We cannot verify it, so we will not
    # pretend the artefact satisfies it." Returning None here instead would
    # silently pass every BINDING key it does not branch on -- "font", and
    # every CV-engine key (max_pages, max_bytes, language, prohibited_content,
    # required_fields) -- reporting compliance that was never checked. That is
    # the same defect class as an unsatisfiable rule, in the more dangerous
    # direction: a permanent block is visible, a false pass is not.
    return LetterConstraintViolation(
        rule, f"no letter check exists for constraint key {rule.key!r}"
    )


def _render_field_mapped(content: LetterContent) -> RenderedArtifact:
    mapped: dict[str, object] = {
        unit.answers_question: unit.text for unit in content.units if unit.answers_question
    }
    payload_bytes = str(mapped).encode()
    return RenderedArtifact(
        variant="FIELD_MAPPED",
        pdf_bytes=None,
        field_mapped=mapped,
        page_count=None,
        byte_size=len(payload_bytes),
    )


def _render_pdf(
    content: LetterContent,
    *,
    template: str,
    variant: str,
    context: dict[str, object] | None = None,
) -> RenderedArtifact:
    # render_html_to_artifact, never a bare HTML(...).write_pdf(): it carries
    # url_fetcher=_no_fetch (no network from the render path) and runs
    # scrub_pdf_metadata via _pdf_artifact. Hand-rolling this is how a letter
    # PDF would ship with toolchain metadata and a live SSRF surface that the
    # CV path does not have.
    html = render_to_string(template, {"content": content, **(context or {})})
    # Fix 1: the real variant, not a hardcoded "LETTER_PDF" -- a
    # TWO_SECTION_FORM render must not report itself as a LETTER_PDF.
    # render.py's own contract (RenderedArtifact/UnsupportedRenderVariant
    # docstrings): an artefact must never misreport what was actually
    # rendered.
    return render_html_to_artifact(html, variant=variant)


def render_letter(
    content: LetterContent,
    *,
    structure: str,
    constraints: tuple[ConstraintRule, ...] = (),
    questions: list[dict[str, object]] | None = None,
    shape: LetterShape | None = None,
    funder_kind: str = "",
    addressee: str = "",
    applicant_name: str = "",
    place_and_date: str = "",
) -> RenderedArtifact:
    """Render the letter, inside the shape the page stated.

    `shape` is optional and every existing call path is unchanged without it.
    The three strings beside it are the formal letter's head and foot, which
    only a caller knows: the committee the prompt names, the applicant's name
    from the ledger, and the place-and-date line (the place is the student's,
    and the month name is their language's -- `cv_dates` is an English,
    deliberately locale-independent table, so this module does not format it).

    `funder_kind` is `ApplicationPrompt.funder_kind`, and it is deliberately
    NOT the resolved reader. `_shape_instructions` tells the model "the date,
    addressee, salutation and sign-off are added at render, so do not write
    them" whenever `formality_for(document_language, reader_for(funder_kind))`
    finds a row -- so a caller that resolved the reader itself, or left it at
    the old empty default, produced a letter with no opening and no close and
    no error anywhere. Both sides now reach `reader_for` from the one prompt
    field, which is the only thing that keeps the promise and the render in
    step.
    """
    reader = reader_for(funder_kind)
    # Same hygiene pass CV rendering gets, plus claim-span re-anchoring
    # (Fix 2): without it, invisible characters, bidi overrides and mojibake
    # reach the letter PDF, and the vendored script-aware cleaner never runs
    # on letter prose.
    clean = hygienic_letter_content(content)
    form = shape.form if shape is not None else "ESSAY"
    formality = formality_for(clean.language, reader) if form == "FORMAL_LETTER" else None
    if form == "FORMAL_LETTER" and formality is None and select_letter_variant(
        structure, form=form
    ) == "LETTER_FORMAL":
        # Falls back to the essay template rather than borrowing another
        # language's salutation (spec section 6). Logged, because the missing
        # row is a research finding: the language and the reader are counted,
        # never any text. Only where a formal template would actually have
        # been used -- a portal form and the prescribed research form have
        # nowhere to put a salutation, so warning about them said something
        # false and polluted the signal (review 2).
        logger.warning(
            "letter formalities: no usable row for language %r and reader %r, "
            "rendering as an essay",
            clean.language,
            reader,
        )
    if formality is None:
        form = "ESSAY"
    variant = select_letter_variant(structure, form=form)
    if (
        shape is not None
        and shape.font_family
        and variant in _TEMPLATE_BY_VARIANT
        and shape.font_family not in SHIPPED_FONTS
    ):
        # After the variant is known, because the check is about a font that
        # will be APPLIED: FIELD_MAPPED is text typed into someone else's
        # portal box and has no font at all, and blocking it claimed a
        # substitution that could not happen (review 2). Still before any
        # rendering: nothing after this satisfies a font we do not have.
        raise PreflightBlocked(
            f"letter font {shape.font_family!r} is not shipped; "
            f"rendering it would substitute one of {sorted(SHIPPED_FONTS)}"
        )
    rendered = _rendered_units(clean, variant)
    if variant == "FIELD_MAPPED":
        answered = [unit.answers_question for unit in clean.units if unit.answers_question]
        if len(answered) != len(set(answered)):
            # The same refusal TWO_SECTION_FORM makes, for the same reason:
            # two units answering one question send ONE answer to the portal,
            # so approved text disappears with no error (re-review). The
            # silent drop this path does allow is a unit with NO question --
            # there the portal has no box; here it has one and the earlier
            # answer is thrown away.
            duplicated = sorted({q for q in answered if answered.count(q) > 1})
            raise PreflightBlocked(
                f"two answers for one portal question: {', '.join(duplicated)}"
            )
        if questions is not None:
            asked = {str(question["id"]) for question in questions}
            unasked = sorted(q for q in answered if q not in asked)
            if unasked:
                # The third case: not "a unit with no question" (the portal has
                # no box, and that drop is deliberate) but a unit answering a
                # question the portal never asked. It renders into a key
                # nobody reads while the real question goes unanswered, and
                # the length checks measure text no reader receives.
                raise PreflightBlocked(
                    f"answers to questions this portal does not ask: {', '.join(unasked)}"
                )
    if variant == "TWO_SECTION_FORM" and len(rendered) != len(clean.units):
        # Fail loudly rather than dropping approved content. The form has
        # exactly two boxes and they are exactly the two archetypes this
        # structure's own playbook writes, so a third one is not "an
        # archetype this form excludes by design" -- it is a prompt whose
        # archetype list and whose structure disagree, and the counselor
        # approved text that would vanish from the PDF.
        unplaceable = sorted({u.archetype for u in clean.units} - _TWO_SECTION_ARCHETYPES)
        raise PreflightBlocked(
            f"two-section form has no section for: {', '.join(unplaceable)}"
        )
    # FIELD_MAPPED deliberately does NOT raise for its own drop: a
    # SHORT_ANSWER_SET answer must map to a specific portal question, and
    # LetterUnit.answers_question is nullable by design, so a unit with no
    # question is a shape the schema allows and the portal has no box for.
    # Narrowing the measurement is the fix there; blocking the whole render
    # because a model volunteered an unasked-for OPENING would be a quality
    # problem turned into a hard failure. Task 6's PROMPT_REQUIREMENT_UNMET
    # gate still covers the opposite direction -- a question nothing answered.
    # The APPLICANT'S text, not the finished document: the salutation, closing
    # and date a formal render adds are ours, and M-016 -- the one row that
    # renders them -- pre-prints exactly those and caps the body the applicant
    # writes. Stated because it is a real gap in the other direction, measured
    # at 51-80 characters (review 1): at a 1,000-character cap the printed page
    # can pass this check and overrun the page's own limit. `target_word_count`
    # aiming at 85% of a cap is what absorbs it today.
    text_for_checks = _full_text(rendered)
    binding_violations = [
        v
        for rule in constraints
        if (v := _check_letter_constraint(rule, text=text_for_checks)) is not None
        and rule.enforcement == Enforcement.BINDING
    ]
    if binding_violations:
        # The page's own sentence travels with the violation: these rules are
        # built from the shape, so "500 words exceeds 450" alone leaves the
        # reader of the log guessing which page said 450. Capped, because
        # rule_text is untrusted page content.
        # normalize_text and !r, not raw: rule_text is verbatim page content
        # on a new channel, and a sentence carrying ANSI escapes plus a newline
        # forged a second, exculpatory violation entry in this very message
        # (review 2). The cap bounds volume; these two bound characters.
        detail = "; ".join(
            f"{v.rule.rule_id}: {v.detail} ({normalize_text(v.rule.rule_text)[:200]!r})"
            for v in binding_violations
        )
        raise PreflightBlocked(detail)
    if variant == "FIELD_MAPPED":
        for rule in constraints:
            if rule.key in _ARTIFACT_CONSTRAINT_KEYS and rule.enforcement == Enforcement.BINDING:
                # Fail closed, matching _check_letter_constraint's own rule:
                # it returns None for these keys on the promise that
                # render_letter measures them against the artefact, and a
                # portal form has no artefact to measure (review 1). A page
                # cap on a portal form may well be meaningless -- saying so is
                # this module's policy, returning silently is not.
                raise PreflightBlocked(
                    f"{rule.rule_id}: a portal form has no artefact, so {rule.key} "
                    "cannot be checked"
                )
        field_mapped = _render_field_mapped(clean)
        # Pass prompt.questions here: document-level constraints above cannot
        # express a per-question cap, and this is the common funder shape.
        _check_question_limits(field_mapped, questions)
        return field_mapped
    artifact = _render_pdf(
        clean,
        template=_TEMPLATE_BY_VARIANT[variant],
        variant=variant,
        context=letter_context(
            shape,
            formality=formality,
            addressee=addressee,
            applicant_name=applicant_name,
            place_and_date=place_and_date,
        ),
    )
    # Page and byte limits can only be measured after rendering, and render.py
    # already measures them. Reusing its checkers here is what shrinks the
    # fail-closed set in _check_letter_constraint to genuinely unmeasurable
    # keys instead of blocking every funder with a page limit.
    for rule in constraints:
        if rule.key in _ARTIFACT_CONSTRAINT_KEYS and rule.enforcement == Enforcement.BINDING:
            artifact_detail = _CHECKERS[rule.key](rule, clean, artifact)
            if artifact_detail is not None:
                raise PreflightBlocked(f"{rule.rule_id}: {artifact_detail}")
    return artifact
