"""Text out of a PDF, for anything in this codebase that has PDF bytes.

It lives in research rather than in documents because the import direction is
documents -> research and never the reverse (reader.py's own docstring, and
program_rules.py exists for that reason alone). The programme reader fetches
`application/pdf` sources -- egress allows the type -- and before this it
decoded them as UTF-8 and handed the model mojibake.

The pypdf call, its error set and both text repairs -- the invented kerning
space and the sub/superscript join -- were measured and hardened on the
student-upload path (`documents.ingestion.extract_text`, which now calls
this). Nothing about them is research-specific: they are properties of pypdf's
text layer, and a chemistry programme page carries "(PMe3)" exactly as a
student's CV does. Only the exception they raise is documents-specific, so
ingestion translates it back to UnsupportedUpload.
"""

from __future__ import annotations

import io
import re

from pypdf import PdfReader
from pypdf.errors import PyPdfError

#: pypdf's own PyPdfError hierarchy undercounts it. Measured: 300 PdfWriter-produced
#: PDFs, each given 10 random byte flips, raised PyPdfError 228 times but
#: AttributeError 20 times and ValueError 8 times -- both out of pypdf's own
#: recovery code, not its PyPdfError hierarchy (e.g. PdfReader.__init__'s
#: `cast(DictionaryObject, ...).get("/Type")` on an object that turns out not
#: to be a dict; _find_startxref_pos's `int(line[9:].strip())` on a corrupted
#: offset). Scoped to the reader call only, never exported as _UNREADABLE's
#: replacement: AttributeError and ValueError are also what a bug in our own
#: code raises, and this must not spread past the pypdf call.
_PDF_READ_ERRORS = (PyPdfError, AttributeError, ValueError)

#: A space pypdf invented, removed again: its extraction emits one wherever a
#: text operator's kerning adjustment crosses a threshold, so a tightly kerned
#: producer yields "Scikit -learn" and "Abdullayev ," from a document holding
#: neither. Still present in 6.17.0, re-measured on the merge.
#:
#: Two things here a future editor would otherwise undo. It is NOT ":" or ";":
#: French typography requires a space before those, and this platform's
#: students write French, so a rule phrased over "punctuation" corrupts correct
#: text. And pypdf's "layout" mode, which fixes this at the source, is rejected
#: -- it drops required spaces on other producers, and this function also feeds
#: evidence intake, which reads exactly those documents.
#:
#: Producer survey, the rejected alternatives and the measurements:
#: docs/superpowers/specs/2026-09-11-pdf-text-extraction-repair-design.md.
_KERNED_SPACE = re.compile(r"(?<=\w) (?=-\w|[,.](?:\s|$))")

#: Private Use Area, where a symbol font's glyphs land: Wingdings list bullets
#: come out as U+F0B7 and mean nothing to a reader. Measured 2026-09-18 on two
#: real documents -- DAAD's EPOS checklist carries 44 of them and Fulbright
#: Nepal's sample CV 17, and poppler passes exactly the same count through, so
#: this is the document's own encoding rather than pypdf misreading it.
#: Dropped to a space, never to "- ": a PUA glyph can be a checkbox, an arrow
#: or a logo, and inventing a list marker is a claim about the page.
#: The upload path never saw these (documents.hygiene.normalize_text already
#: removes them); the research reader hands its text straight to a model.
_SYMBOL_GLYPH = re.compile(r"[\ue000-\uf8ff]+")


#: A sub/superscript is set in its own, smaller text run, and pypdf puts a
#: space in front of it. Measured on a real CV: "(PMe3)" comes out of the text
#: layer as "(PMe 3)" -- the "3" is a separate run at 8.04pt against 12.0pt
#: body text. Downstream that is worse than cosmetic, because the model is
#: told to copy: one run reproduced "(PMe 3)" and another moved the space to
#: "( PMe3)", so the same document rendered two different wrong strings.
#:
#: The FONT SIZE is what makes this safe, and it is available only here, in
#: the visitor -- by the time the text is a string, "PMe 3" and "Python 3" are
#: the same shape. Both further conditions are load-bearing: a run 4 characters
#: or shorter excludes a footnote or caption paragraph merely set in smaller
#: type, whose first word would otherwise be glued to the line above; and
#: alphanumeric excludes a small-type run opening with punctuation.
_SUB_SUPERSCRIPT_RATIO = 0.85
_MAX_SUBSCRIPT_CHARS = 4


def _subscript_joins(reader: PdfReader) -> list[tuple[str, str]]:
    """(text before, subscript run) pairs whose space pypdf invented.

    `before` is the trailing non-space chunk of the preceding run, which is
    what makes the later replacement exact rather than global: it rewrites
    "(PMe 3" and leaves every other " 3" in the document alone. A run that
    starts a line has no preceding run on that line, so its pair simply never
    matches -- no guard needed.
    """
    spans: list[tuple[str, float]] = []

    def visit(text: str, cm: object, tm: object, font: object, size: float) -> None:
        if text.strip():
            spans.append((text, float(size)))

    for page in reader.pages:
        page.extract_text(visitor_text=visit)
    joins = []
    for (before, before_size), (run, size) in zip(spans, spans[1:]):
        body = run.strip()
        if (
            run.startswith(" ")
            and size < _SUB_SUPERSCRIPT_RATIO * before_size
            and len(body) <= _MAX_SUBSCRIPT_CHARS
            and body.isalnum()
        ):
            joins.append((before.split()[-1] if before.split() else "", run))
    return joins


class PdfUnreadable(ValueError):
    """pypdf could not read these bytes: truncated, encrypted, or corrupt."""


def pdf_text(content: bytes) -> str:
    """The text layer of a PDF, with pypdf's invented kerning spaces removed.

    Isolates the pypdf reader call so its exception set can be wider than a
    caller's own: see _PDF_READ_ERRORS. Both repairs stay on this branch
    because a DOCX carries no text positioning to misread.

    An empty string is a real answer -- a scanned PDF has no text layer -- and
    callers must not read it as "this document says nothing".
    """
    try:
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        joins = _subscript_joins(reader)
    except _PDF_READ_ERRORS as error:
        # No filename, no bytes and no reader message in the text: an
        # exception message is a log line, and this one is about a document.
        raise PdfUnreadable("pdf could not be read") from error
    # Subscripts first, then the kerning repair, then the symbol glyphs: the
    # joins are matched against the runs pypdf emitted, so anything that
    # rewrites the text has to come after them.
    for before, run in joins:
        if before:
            text = text.replace(before + run, before + run.lstrip(), 1)
    return _SYMBOL_GLYPH.sub(" ", _KERNED_SPACE.sub("", text))
