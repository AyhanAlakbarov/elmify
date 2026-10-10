"""How accurately a CV is read, measured rather than asserted.

Two tiers, because the expensive one cannot run on every push:

* The default tier costs nothing and runs in CI. It scores `parse_cv_date`
  against every date form the corpus prints, so a change to the format table
  cannot silently drop a shape the evaluation depends on. This is the check
  that holds the line day to day.
* The `live` tier runs the real extraction against the real API and asserts the
  measured floors below. It is excluded by `pyproject.toml`'s
  `addopts = "-m 'not live'"` and skips without a key, so it is a
  before-you-merge check, not a per-push one.

The floors are what was measured on 2026-08-31 over eight documents and two
runs each: entries 59/60, dates 118/118, names 16/16, languages 16/16
(docs/superpowers/research/2026-08-31-cv-extraction-baseline.md). Entries are a
floor rather than an equality because one keyed entry is genuinely ambiguous --
a high school listed with a year and no qualification, which one run of two
dropped. Dates are an equality: every date form here has one right reading, and
53% of them were being dropped a commit ago.

A failure here is not automatically a regression in this repo. The model can
change under us, which is exactly what this tier exists to detect -- but read
the diff before concluding which side moved.
"""

from __future__ import annotations

import os
import unicodedata

import pytest

from apps.documents.dates import date_convention, parse_cv_date
from apps.documents.ingestion import _extract_claims, extract_link_urls, extract_text

from .cv_corpus import CORPUS

#: Measured 2026-08-31. Entries: 59/60 over eight documents.
_MIN_ENTRY_RECALL = 0.95


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join("".join(c for c in text if c.isalnum() or c.isspace()).split())


def _same(left: object, right: object) -> bool:
    """Tolerant on wording, strict on identity: "AB in Computer Science" must
    match "A.B. in Computer Science" without matching "High School Diploma"."""
    a, b = _norm(left), _norm(right)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    first, second = set(a.split()), set(b.split())
    return len(first & second) / max(len(first), len(second)) >= 0.6


@pytest.mark.parametrize(
    "doc_name,written,position,expected",
    [
        (name, written, position, expected)
        for name, doc in CORPUS.items()
        for written, position, expected in doc.dates
    ],
)
def test_every_date_form_the_corpus_prints_is_read(doc_name, written, position, expected):
    """No model call. The evaluation's claim rests on these forms parsing, so
    they are pinned separately from the generic table in test_cv_date_parsing."""
    token = date_convention.set(CORPUS[doc_name].convention)
    try:
        parsed = parse_cv_date(written, position=position)
    finally:
        date_convention.reset(token)
    assert (parsed.isoformat() if parsed else None) == expected


def test_every_document_renders_a_readable_pdf():
    """The corpus is built at test time; a document that produces no text layer
    would make the live tier measure nothing and pass."""
    for name, doc in CORPUS.items():
        text = extract_text(doc.pdf())
        assert doc.full_name in text, name
        assert len(text) > 200, name


def _score(doc, content):
    """(entries found, entries keyed, dates right, dates checked) for one run."""
    found = keyed = right = checked = 0
    for section, got, label_of in (
        (doc.education, content.education,
         lambda e: (e.degree_as_awarded, e.institution_original)),
        (doc.experience, content.experience, lambda e: (e.title, e.employer)),
    ):
        used: set[int] = set()
        for want_label, want_org, want_start, want_end in section:
            keyed += 1
            match = next(
                (
                    (i, entry)
                    for i, entry in enumerate(got)
                    if i not in used
                    and _same(want_org, label_of(entry)[1])
                    and (not want_label or _same(want_label, label_of(entry)[0]))
                ),
                None,
            )
            if match is None:
                continue
            index, entry = match
            used.add(index)
            found += 1
            for field, want in (("start_date", want_start), ("end_date", want_end)):
                checked += 1
                value = getattr(entry, field)
                got_iso = value.isoformat() if value else None
                # Prefix comparison: a key of "2023-06" accepts any day in June
                # 2023, because the page named a month and no day.
                if (want is None and got_iso is None) or (
                    want is not None and got_iso is not None and got_iso.startswith(want)
                ):
                    right += 1
    return found, keyed, right, checked


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs a live API key")
def test_the_corpus_is_read_at_the_measured_accuracy():
    """One extraction per document, six model calls.

        OPENAI_API_KEY=... POSTGRES_DB=... uv run pytest \\
            tests/documents/test_extraction_accuracy.py -m live
    """
    from openai import OpenAI

    client = OpenAI()
    found = keyed = right = checked = 0
    names_right = langs_right = 0
    failures: list[str] = []

    for name, doc in CORPUS.items():
        raw = doc.pdf()
        content = _extract_claims(
            client.responses,
            student_id=f"corpus-{name}",
            text=extract_text(raw),
            link_urls=extract_link_urls(raw),
        )
        assert content is not None, f"{name}: extraction produced nothing"
        doc_found, doc_keyed, doc_right, doc_checked = _score(doc, content)
        found, keyed, right, checked = (
            found + doc_found,
            keyed + doc_keyed,
            right + doc_right,
            checked + doc_checked,
        )
        if doc_found < doc_keyed:
            failures.append(f"{name}: {doc_found}/{doc_keyed} entries")
        if doc_right < doc_checked:
            failures.append(f"{name}: {doc_right}/{doc_checked} dates")
        names_right += int(_same(doc.full_name, content.personal_information.full_name))
        langs_right += int(
            {_norm(entry.language) for entry in content.languages}
            == {_norm(language) for language in doc.languages}
        )

    report = "; ".join(failures) or "no per-document shortfalls"
    assert found / keyed >= _MIN_ENTRY_RECALL, f"entries {found}/{keyed} -- {report}"
    assert right == checked, f"dates {right}/{checked} -- {report}"
    assert names_right == len(CORPUS), f"names {names_right}/{len(CORPUS)}"
    assert langs_right == len(CORPUS), f"languages {langs_right}/{len(CORPUS)}"
