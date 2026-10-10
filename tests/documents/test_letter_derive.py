import csv
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.documents.derive import (
    _PHRASINGS,
    Candidate,
    Derivations,
    LetterVerdict,
    _touches_cv,
    _touches_letter,
    candidates,
    decide,
    outcomes,
)


def test_a_german_page_finds_its_letter_lines_by_the_german_row() -> None:
    page = (
        "# Bewerbung\n"
        "Das Motivationsschreiben darf maximal zwei Seiten umfassen.\n"
        "Bitte laden Sie Ihren Lebenslauf hoch.\n"
    )
    found = candidates(page, (), language="de")
    letters = [c.text for c in found if c.letter]
    assert letters == ["Das Motivationsschreiben darf maximal zwei Seiten umfassen."]
    # The CV line is still a CV candidate and is not a letter candidate.
    assert [c.text for c in found if c.cv and not c.letter] == [
        "Bitte laden Sie Ihren Lebenslauf hoch."
    ]


def test_a_reader_label_is_a_letter_candidate_in_any_language() -> None:
    """Spec §3: a language with a thin row loses nothing the reader labelled."""
    statement = "Kérjük, csatoljon egy motivációs levelet."  # Hungarian: no row
    found = candidates("# Felvételi\nsemmi\n", (statement,), language="")
    assert [(c.text, c.letter, c.cv) for c in found] == [(statement, True, True)]


def test_one_sentence_can_be_both_documents() -> None:
    page = "Submit a CV and a letter of motivation of at most 500 words.\n"
    (found,) = candidates(page, (), language="en")
    assert found.cv and found.letter


def test_a_letter_line_about_a_referee_is_marked_third_party() -> None:
    page = "Your referee must upload a letter of recommendation of one page.\n"
    (found,) = candidates(page, (), language="en")
    assert found.letter and found.third_party


def test_an_unknown_language_finds_no_letter_line_by_keyword() -> None:
    page = "Kérjük, csatoljon egy motivációs levelet legfeljebb 500 szóban.\n"
    assert candidates(page, (), language="") == ()


def test_a_letter_only_line_cannot_abstain_the_cv_decision() -> None:
    """The shared listing must not let one document's silence blank the other."""
    found = candidates(
        "Submit a Europass CV.\nThe letter must be one page.\n", (), language="en"
    )
    # One sample judges only the CV line; the letter line is unjudged for the CV.
    sample = Derivations(
        formats=({"statement_index": 0, "value": "required"},),  # type: ignore[arg-type]
    )
    decision = decide(found, [sample, sample, sample], source_url="u")

    assert decision.abstained is False


def test_a_letter_only_line_is_absent_from_the_too_few_samples_abstention() -> None:
    """Fix round 1, finding 1: zero samples forces the early len(samples) <
    _SAMPLES - 1 abstain path, which built its synthetic `per` over every
    candidate. A letter-only line must not surface there as an undecided CV
    rule -- it was never a CV sentence."""
    found = (
        Candidate(text="Submit a Europass CV.", heading="", europass=True, cv=True, letter=False),
        Candidate(
            text="The letter must be one page.", heading="", europass=False, cv=False, letter=True
        ),
    )
    decision = decide(found, [], source_url="u")

    assert decision.abstained is True
    assert decision.rules
    assert all(r.rule_text == "Submit a Europass CV." for r in decision.rules)


def test_newsletter_is_not_a_letter_candidate() -> None:
    """Fix round 1, finding 2: substring containment let 'letter' match inside
    'newsletter'; the compiled pattern is word-bounded like _CV_TERMS."""
    page = "Our newsletter explains the application steps.\n"
    assert candidates(page, (), language="en") == ()


def test_a_letter_of_motivation_line_is_still_found() -> None:
    page = "Submit a letter of motivation.\n"
    (found,) = candidates(page, (), language="en")
    assert found.letter


def test_a_japanese_letter_term_with_no_surrounding_spaces_is_still_found() -> None:
    """CJK terms are matched unanchored -- these scripts have no spaces, so a
    word-bounded pattern would never match real text."""
    page = "志望理由書を提出してください。\n"
    (found,) = candidates(page, (), language="ja")
    assert found.letter


def test_a_long_page_is_capped_at_the_judges_ceiling(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every Derivations list is max_length=100, so a 101st candidate can
    never come back judged; the cap makes that explicit instead of letting a
    long or hostile page build a listing nothing can answer."""
    page = "\n".join(f"Your CV needs revision {i}." for i in range(150))
    with caplog.at_level(logging.WARNING):
        found = candidates(page, (), language="en")
    assert len(found) == 100
    assert sum("page yielded" in record.message for record in caplog.records) == 1


def test_a_letter_verdict_is_closed_and_typed() -> None:
    verdict = LetterVerdict(
        statement_index=0, subject="applicant_letter", length_measure="words",
        length_bound="maximum", length_number=500, form="formal_letter", naming="forbidden",
    )
    assert verdict.length_number == 500 and verdict.form == "formal_letter"
    with pytest.raises(ValidationError):
        LetterVerdict(statement_index=0, subject="applicant_letter", form="haiku")
    with pytest.raises(ValidationError):
        LetterVerdict(statement_index=0, subject="applicant_letter", unknown_field=1)


def test_a_letter_verdict_alone_is_touches_letter_not_touches_cv() -> None:
    """Fix round 1, finding 2: a shared _touches let a letter verdict stand in
    for a CV answer that never came, weakening abstain()'s page-abstention
    guarantee. _touches_cv and _touches_letter are scoped per document."""
    sample = Derivations(
        letters=(LetterVerdict(statement_index=3, subject="applicant_letter"),)
    )
    assert _touches_letter(sample, 3) and not _touches_cv(sample, 3)
    assert not _touches_letter(sample, 4) and not _touches_cv(sample, 4)


def test_a_letter_verdict_alone_leaves_the_cv_line_unjudged() -> None:
    """Fix round 1, finding 2's missing regression: a reading that answers the
    letter question but not the CV one for the same line must not look like
    it judged the CV -- outcomes() marks the line unjudged and decide()
    abstains the page."""
    found = (Candidate(text="Submit a CV.", heading="", europass=False, cv=True, letter=False),)
    sample = Derivations(letters=(LetterVerdict(statement_index=0, subject="applicant_letter"),))
    samples = [sample, sample, sample]

    per = outcomes(found, samples)
    assert per[0].kind == "unjudged"

    decision = decide(found, samples, source_url="u")
    assert decision.abstained is True


def test_every_phrasing_states_the_letter_question_and_the_data_framing() -> None:
    for phrasing in _PHRASINGS:
        assert "DATA" in phrasing
        assert "letter" in phrasing.lower()
        assert "length" in phrasing.lower()


_EVAL = Path(__file__).resolve().parents[2] / "docs/research/letter-shape-eval.csv"

#: An expected field on the eval sheet, as the LetterVerdict fields that carry
#: it. A length row is three assertions (measure, bound, number) because a
#: right number under the wrong measure is a wrong cap, not a near miss.
_LENGTH = {
    "max_words": ("words", "maximum"),
    "min_words": ("words", "minimum"),
    "max_chars": ("characters", "maximum"),
    "max_pages": ("pages", "maximum"),
}


def _asserted(verdict: LetterVerdict, field: str, value: str) -> bool | None:
    """Whether this reading asserted the expected value, contradicted it, or
    said nothing (None)."""
    if field in _LENGTH:
        measure, bound = _LENGTH[field]
        if verdict.length_measure == "none" and verdict.length_number is None:
            return None
        return (
            verdict.length_measure == measure
            and verdict.length_bound == bound
            and verdict.length_number == int(value)
        )
    got = getattr(verdict, field)
    if got in ("none", None, False):
        return None
    if field in ("handwritten", "signed_declaration"):
        return got is True
    return str(got) == value


@pytest.mark.live
def test_the_judge_reads_every_language_in_the_eval_sheet(capsys) -> None:
    """Per-language recall and precision, printed per language, never averaged.

    The bar: zero wrong caps and zero missed naming=forbidden, in every
    language present. Re-run before any change to the judge prompt.

    A row whose `expected_field` is `none` states something the shape cannot
    type -- a byte cap, a page cap of 1.5 (the schema's length_number is an
    integer), a rule about who may write the letter. Those are PRINTED and not
    asserted: what the judge does with them is the finding, and pinning it
    would freeze an answer nobody has decided yet.
    """
    openai = pytest.importorskip("openai")
    anthropic = pytest.importorskip("anthropic")
    from django.conf import settings

    from apps.documents.derive import _judge, _verdicts_for

    rows = list(csv.DictReader(_EVAL.open(encoding="utf-8")))
    by_language: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_language.setdefault(row["language"], []).append(row)

    wrong_caps: list[tuple[str, str, str]] = []
    missed_forbidden: list[str] = []
    with capsys.disabled():
        print(f"\n{settings.OPENAI_EXTRACTION_MODEL} x2 + {settings.ANTHROPIC_JUDGE_MODEL}")
    for language, language_rows in sorted(by_language.items()):
        page_text = "\n".join(row["sentence"] for row in language_rows)
        found = candidates(page_text, (), language=language)
        index_of = {candidate.text: index for index, candidate in enumerate(found)}
        listing = "\n".join(f"{index} | {c.text}" for index, c in enumerate(found))
        samples = _judge(
            openai.OpenAI().responses,
            anthropic.Anthropic().messages,
            program_id=f"eval-{language}",
            listing=listing,
        )
        asserted = missed = contradicted = unfound = printed = 0
        for row in language_rows:
            index = index_of.get(row["sentence"])
            if index is None:
                # Found by no recall path: a real result about the SHEET, not
                # about the judge, so it is counted and named separately.
                unfound += 1
                continue
            answers = [
                _asserted(verdict, row["expected_field"], row["expected_value"])
                for verdict in _verdicts_for(samples, index)
            ]
            if row["expected_field"] == "none":
                printed += 1
                with capsys.disabled():
                    print(f"  ? {row['id']} [{language}] untypeable -> {answers}")
                continue
            if any(answer is False for answer in answers):
                contradicted += 1
                if row["expected_field"] in _LENGTH:
                    wrong_caps.append((row["id"], language, row["expected_field"]))
            elif any(answer is True for answer in answers):
                asserted += 1
            else:
                missed += 1
                if row["expected_field"] == "naming" and row["expected_value"] == "forbidden":
                    missed_forbidden.append(row["id"])
        with capsys.disabled():
            print(
                f"  {language}: {len(language_rows)} rows, {asserted} asserted, "
                f"{missed} missed, {contradicted} contradicted, {unfound} not a candidate, "
                f"{printed} untypeable"
            )
    assert wrong_caps == []
    assert missed_forbidden == []


def test_the_eval_sheet_is_well_formed() -> None:
    """Runs without a model, because a broken sheet must not wait for a paid run."""
    rules = {
        row["ID"]
        for row in csv.DictReader(
            (_EVAL.parent / "letter-shape-rules.csv").open(encoding="utf-8")
        )
    }
    rows = list(csv.DictReader(_EVAL.open(encoding="utf-8")))
    assert len(rows) >= 60
    assert len({row["id"] for row in rows}) == len(rows)
    fields = set(_LENGTH) | {
        "form",
        "naming",
        "handwritten",
        "signed_declaration",
        "font_min_pt",
        "line_spacing",
        "margins_cm",
        "document_required",
        "file_bundle",
        "none",
    }
    for row in rows:
        assert row["expected_field"] in fields, row
        assert row["rule_id"] in rules, row
        # http:// as well as https://: one catalogued source (Cairo
        # University) publishes over http, and rewriting a provenance URL to
        # make a test pass is how provenance stops being provenance.
        assert row["source_url"].startswith(("https://", "http://")), row
        assert row["wording"] in ("catalog", "reconstructed"), row
        assert bool(row["expected_value"]) is (row["expected_field"] != "none"), row
    # More than one language, and the sheet says which sentences are the
    # catalog's own words and which were rebuilt around a quoted fragment.
    assert len({row["language"] for row in rows}) >= 5
    assert {row["wording"] for row in rows} == {"catalog", "reconstructed"}


def test_every_expected_value_is_readable_by_the_gates_own_mapping() -> None:
    """A value the gate cannot compare is a row that silently asserts nothing."""
    for row in csv.DictReader(_EVAL.open(encoding="utf-8")):
        field, value = row["expected_field"], row["expected_value"]
        if field in _LENGTH:
            assert int(value) > 0
        elif field in ("handwritten", "signed_declaration"):
            assert value == "true"
        elif field == "font_min_pt":
            assert 4 <= int(value) <= 40
        elif field == "line_spacing":
            assert value in ("1.0", "1.5", "2.0")
        elif field == "naming":
            assert value in ("required", "invited", "forbidden")
        elif field == "form":
            assert value in ("essay", "formal_letter", "portal_form")


def test_every_letter_verdict_field_is_sent_as_required():
    """Measured live 2026-09-25: with its defaulted fields optional, Anthropic
    refused the whole Derivations schema ("Schema is too complex", HTTP 400),
    which crashed every page read that had ANTHROPIC_API_KEY set. Sent as
    required, it is accepted; the Python defaults still build partial verdicts."""
    schema = LetterVerdict.model_json_schema()
    assert sorted(schema["required"]) == sorted(schema["properties"])
    assert LetterVerdict(statement_index=0).subject == "other"
