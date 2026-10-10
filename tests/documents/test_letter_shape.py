import pytest

from apps.documents.derive import Candidate, Derivations, LetterVerdict, decide_letter_shape
from apps.documents.letter_gates import check_language_mismatch
from apps.documents.letter_schemas import LetterContent, LetterUnit
from apps.documents.letter_shape import LetterShape, apply_derived_shape, shape_from_prompt
from apps.funding.models import ApplicationPrompt, CatalogWriteBlocked, Program

from .conftest import make_program


@pytest.fixture
def program() -> Program:
    # Fix round 1, finding 6: this used to build its own Institution/Program
    # pair by hand; collapsed into tests/documents/conftest.py's make_program
    # alongside the same builder in test_letters.py and
    # test_letter_end_to_end.py. Country DE is this file's own convention,
    # kept -- nothing here asserts on institution/programme name or city.
    return make_program(country_code="DE")


def _line(text: str = "The letter must be short.", **kwargs) -> Candidate:
    return Candidate(text=text, heading="", europass=False, cv=False, letter=True, **kwargs)


def _sample(**kwargs) -> Derivations:
    # setdefault, not a literal keyword: the brief's own literal form
    # (`LetterVerdict(statement_index=0, subject="applicant_letter", **kwargs)`)
    # raises TypeError the moment a test passes `subject=` itself (as
    # test_a_referees_letter_sets_nothing does), from a plain keyword/**kwargs
    # collision -- nothing to do with the derivation logic under test.
    kwargs.setdefault("subject", "applicant_letter")
    return Derivations(letters=(LetterVerdict(statement_index=0, **kwargs),))


def _decide(candidate, *samples):
    return decide_letter_shape((candidate,), list(samples), source_url="https://x.example/p")


def test_a_fabricated_number_inside_a_larger_one_does_not_verify() -> None:
    """Fix round 2, finding 1: substring containment let "150" verify against
    "1500" (and "202" against "2027"). The guard must match a whole numeral
    token, so a smaller number that is merely a substring of the real one is
    dropped, not treated as a corroborating (and therefore winning) reading."""
    shape = _decide(
        _line("The letter must not exceed 1500 characters."),
        _sample(length_measure="characters", length_bound="maximum", length_number=1500),
        _sample(length_measure="characters", length_bound="maximum", length_number=150),
        _sample(length_measure="characters", length_bound="maximum", length_number=150),
    )
    assert shape.max_chars == 1500


def test_a_lone_misread_line_never_sets_a_word_cap() -> None:
    """Fix round 2, finding 2: `caps` was a running reduction across every
    line on the page, so ONE reading misreading an unrelated line (a room
    number) as a word limit could set an unsatisfiable cap for the whole
    document. A figure needs a second reading agreeing the line is about
    that measure before it is used; the other two readings correctly saying
    "no length statement here" is exactly the disagreement that must block
    it."""
    shape = _decide(
        _line("Room 12, Building A."),
        _sample(length_measure="words", length_bound="maximum", length_number=12),
        _sample(),
        _sample(),
    )
    assert shape.max_words is None


def test_a_lone_misread_date_never_sets_a_word_cap() -> None:
    shape = _decide(
        _line("Applications close on 1 October."),
        _sample(length_measure="words", length_bound="maximum", length_number=1),
        _sample(),
        _sample(),
    )
    assert shape.max_words is None


def test_two_readings_disagreeing_on_a_cap_take_the_smaller() -> None:
    shape = _decide(
        _line(
            "The motivation letter must not exceed 500 words; applicants to the "
            "research track may write up to 800 words."
        ),
        _sample(length_measure="words", length_bound="maximum", length_number=800),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=800),
    )
    assert shape.max_words == 500


def test_one_reading_finding_a_floor_keeps_it() -> None:
    shape = _decide(
        _line("Letters below 500 words will not be accepted."),
        _sample(length_measure="words", length_bound="minimum", length_number=500),
        _sample(),
        _sample(),
    )
    assert shape.min_words == 500


def test_approximate_wording_is_a_cap_and_never_a_floor() -> None:
    shape = _decide(
        _line("The letter should be about 1 page."),
        _sample(length_measure="pages", length_bound="approximate", length_number=1),
        _sample(length_measure="pages", length_bound="approximate", length_number=1),
        _sample(length_measure="pages", length_bound="approximate", length_number=1),
    )
    assert shape.max_pages == 1 and shape.min_words is None


def test_a_count_written_as_a_word_before_its_unit_sets_the_cap() -> None:
    """This test used to pin the opposite, and said when to change it: "If this
    gap is ever measured to matter, the remedy is per-language number words in
    normalise_numerals, never relaxing the guard." Measured live 2026-09-25: ETH
    ("approximately one A4 page"), TUM ("maximal zwei DIN-A4-Seiten") and Eiffel
    ("une ou deux pages") all lost their cap. letter_terms.numbers_on_line now
    reads a small number word standing just before a length unit; the guard is
    not relaxed anywhere else."""
    shape = _decide(
        _line("The letter should be about one page."),
        _sample(length_measure="pages", length_bound="approximate", length_number=1),
        _sample(length_measure="pages", length_bound="approximate", length_number=1),
        _sample(length_measure="pages", length_bound="approximate", length_number=1),
    )
    assert shape.max_pages == 1


def test_a_number_word_far_from_any_unit_still_sets_no_cap() -> None:
    """The safe direction the old test protected, kept: losing a cap costs the
    default target; inventing one ships a letter the page never asked for."""
    shape = _decide(
        _line("One of the documents you upload is the motivation letter."),
        _sample(length_measure="pages", length_bound="maximum", length_number=1),
        _sample(length_measure="pages", length_bound="maximum", length_number=1),
        _sample(length_measure="pages", length_bound="maximum", length_number=1),
    )
    assert shape.max_pages is None


def test_caps_in_two_units_are_both_kept() -> None:
    shape = _decide(
        _line("Maximum 500 words and 3500 characters."),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="characters", length_bound="maximum", length_number=3500),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
    )
    assert shape.max_words == 500 and shape.max_chars == 3500


def test_a_number_not_on_the_page_is_dropped() -> None:
    """Verification removes fabrication here exactly as it does for a quote."""
    shape = _decide(
        _line("The letter must be short."),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
    )
    assert shape.max_words is None


def test_a_number_written_in_another_script_counts_as_on_the_page() -> None:
    shape = _decide(
        _line("志望理由書は五百字以内とします。"),
        _sample(length_measure="characters", length_bound="maximum", length_number=500),
        _sample(length_measure="characters", length_bound="maximum", length_number=500),
        _sample(length_measure="characters", length_bound="maximum", length_number=500),
    )
    assert shape.max_chars == 500


def test_one_reading_saying_letter_makes_it_a_formal_letter() -> None:
    shape = _decide(
        _line("Address the letter to the admissions committee and sign it."),
        _sample(form="formal_letter"), _sample(form="essay"), _sample(form="essay"),
    )
    assert shape.form == "FORMAL_LETTER"


def test_portal_form_needs_every_reading() -> None:
    """A wrongly assumed form drops the letter's prose, so it is the one
    direction that needs unanimity."""
    mixed = _decide(
        _line("Complete the motivation fields in the online form."),
        _sample(form="portal_form"), _sample(form="portal_form"), _sample(form="essay"),
    )
    assert mixed.form == "FORMAL_LETTER"
    unanimous = _decide(
        _line("Complete the motivation fields in the online form."),
        _sample(form="portal_form"), _sample(form="portal_form"), _sample(form="portal_form"),
    )
    assert unanimous.form == "PORTAL_FORM"


def test_one_forbidden_forbids_and_required_needs_all_three() -> None:
    forbidden = _decide(
        _line("References to faculty should not be made in the letter."),
        _sample(naming="forbidden"), _sample(naming="required"), _sample(naming="invited"),
    )
    assert forbidden.naming == "FORBIDDEN"
    invited = _decide(
        _line("You may name a prospective supervisor in the letter."),
        _sample(naming="required"), _sample(naming="invited"), _sample(naming="none"),
    )
    assert invited.naming == "INVITED"
    required = _decide(
        _line("Name the supervisor you wish to work with in the letter."),
        _sample(naming="required"), _sample(naming="required"), _sample(naming="required"),
    )
    assert required.naming == "REQUIRED"


def test_one_reading_is_enough_for_a_signature_and_for_required() -> None:
    shape = _decide(
        _line("The signed letter must be uploaded."),
        _sample(signed_declaration=True, document_required="required"), _sample(), _sample(),
    )
    assert shape.signed_declaration is True
    assert shape.document_required == "REQUIRED"


def test_a_referees_letter_sets_nothing() -> None:
    shape = _decide(
        _line("Your referee uploads a letter of at most one page.", third_party=True),
        _sample(subject="other", length_measure="pages", length_bound="maximum", length_number=1),
        _sample(length_measure="pages", length_bound="maximum", length_number=1),
        _sample(length_measure="pages", length_bound="maximum", length_number=1),
    )
    assert shape.max_pages is None and shape.document_required == "UNSTATED"


def test_every_applied_field_carries_the_sentence_that_set_it() -> None:
    shape = _decide(
        _line("The letter must not exceed 500 words."),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
    )
    assert shape.sources["max_words"]["text"] == "The letter must not exceed 500 words."
    assert shape.sources["max_words"]["source_url"] == "https://x.example/p"


def test_a_writer_path_sentence_is_kept_for_the_prompt_and_the_check() -> None:
    shape = _decide(
        _line("Write the letter in the third person."),
        _sample(requirement_path="writer"),
        _sample(requirement_path="writer"),
        _sample(requirement_path="writer"),
    )
    assert shape.written_requirements[0]["text"] == "Write the letter in the third person."
    assert shape.student_actions == ()


def test_a_student_path_sentence_becomes_an_action_not_a_prompt_line() -> None:
    shape = _decide(
        _line("The letter must be hand-written and signed in ink."),
        _sample(requirement_path="student", handwritten=True),
        _sample(requirement_path="student", handwritten=True),
        _sample(requirement_path="student", handwritten=True),
    )
    assert shape.handwritten is True
    assert shape.student_actions[0]["text"].startswith("The letter must be hand-written")
    assert shape.written_requirements == ()


def test_artifact_fields_take_the_stated_value_and_the_safer_side_of_two() -> None:
    shape = _decide(
        _line("Use Times New Roman 12 pt, 1.5 line spacing and 2 cm margins."),
        _sample(font_family="Times New Roman", font_min_pt=12, line_spacing="1.5", margins_cm=2.0),
        _sample(font_family="Times New Roman", font_min_pt=11, line_spacing="2.0", margins_cm=2.5),
        _sample(font_family="Times New Roman", font_min_pt=12, line_spacing="1.5", margins_cm=2.0),
    )
    assert shape.font_family == "Times New Roman"
    assert shape.font_min_pt == 12  # the larger minimum
    assert shape.line_spacing == 2.0  # of two spacings, the larger
    assert shape.margins_cm == 2.5  # the larger margin


def test_a_hostile_font_family_is_dropped_but_the_rest_of_the_verdict_applies() -> None:
    """font_family is the one model-supplied field that is not a closed set,
    and it later reaches render.py's CSS unescaped. A value that is not plain
    Latin text must be dropped -- and dropped alone, never the whole verdict,
    or a hostile page could abstain the letter's other, harmless fields too."""
    hostile = "Helvetica; } body { background: url(http://evil/"
    shape = _decide(
        _line("Use Helvetica 12 pt."),
        _sample(font_family=hostile, font_min_pt=12),
        _sample(font_family=hostile, font_min_pt=12),
        _sample(font_family=hostile, font_min_pt=12),
    )
    assert shape.font_family is None
    assert shape.font_min_pt == 12


def test_a_second_line_overriding_the_cap_carries_the_second_sentence() -> None:
    """Fix round 2, finding 3: `record()` used `setdefault`, so the FIRST
    line to touch `max_words` kept the attribution even when a LATER line's
    value won. Here the second line's smaller cap must win the VALUE (as
    before) and must also become the recorded SOURCE, not the first line's
    now-superseded sentence."""
    first = _line("The letter must not exceed 800 words.")
    second = _line("In fact the limit is 500 words.")
    shape = decide_letter_shape(
        (first, second),
        [
            Derivations(
                letters=(
                    LetterVerdict(
                        statement_index=0, subject="applicant_letter",
                        length_measure="words", length_bound="maximum", length_number=800,
                    ),
                    LetterVerdict(
                        statement_index=1, subject="applicant_letter",
                        length_measure="words", length_bound="maximum", length_number=500,
                    ),
                ),
            )
            for _ in range(3)
        ],
        source_url="https://x.example/p",
    )
    assert shape.max_words == 500
    assert shape.sources["max_words"]["text"] == second.text


def test_a_second_line_overriding_naming_carries_the_second_sentence() -> None:
    """Same bug as above, for `naming`: the stored quote must match the
    stored decision. A page inviting a supervisor's name on one line and
    forbidding faculty names on another must resolve to FORBIDDEN (the
    safer side) with the source pointing at the FORBIDDING sentence, never
    the superseded "invited" one."""
    first = _line("You may name a prospective supervisor in the letter.")
    second = _line("Do not name any faculty member in the letter.")
    shape = decide_letter_shape(
        (first, second),
        [
            Derivations(
                letters=(
                    LetterVerdict(
                        statement_index=0, subject="applicant_letter", naming="invited"
                    ),
                    LetterVerdict(
                        statement_index=1, subject="applicant_letter", naming="forbidden"
                    ),
                ),
            )
            for _ in range(3)
        ],
        source_url="https://x.example/p",
    )
    assert shape.naming == "FORBIDDEN"
    assert shape.sources["naming"]["text"] == second.text


def test_document_not_required_when_every_reading_agrees() -> None:
    """Fix round 2, finding 5: no test pinned this outcome before."""
    shape = _decide(
        _line("Submitting a letter is optional."),
        _sample(document_required="not_required"),
        _sample(document_required="not_required"),
        _sample(document_required="not_required"),
    )
    assert shape.document_required == "NOT_REQUIRED"


def test_disagreement_on_requirement_path_keeps_both_paths() -> None:
    """Fix round 2, finding 5. On disagreement about WHO a requirement binds
    (two readings say the writer, one says the student), both paths run
    deliberately: the sentence is written into the generation prompt AND
    shown to the student as an action. Either path alone risks losing the
    requirement if that path's own reading turns out to be the wrong guess;
    running both cannot lose it."""
    shape = _decide(
        _line("Keep the letter under two pages, single-spaced, in your own words."),
        _sample(requirement_path="writer"),
        _sample(requirement_path="writer"),
        _sample(requirement_path="student"),
    )
    assert shape.written_requirements != ()
    assert shape.student_actions != ()
    assert shape.written_requirements[0]["text"] == shape.student_actions[0]["text"]


def test_a_misread_digit_elsewhere_on_the_line_does_not_win_the_smaller_cap() -> None:
    """Fix round 3, finding 1: all three readings correctly agree the measure
    is words, so corroboration (finding 2) has nothing to veto -- but one
    reading misreads the cap as the "1" in "page 1" instead of the real 500.
    Both numbers are real tokens on the line, so _number_is_on_the_page
    verifies both, and without a plausibility floor the smaller number (the
    misread 1) would win outright and produce an unsatisfiable cap."""
    shape = _decide(
        _line("The letter must not exceed 500 words. See page 1 for details."),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=1),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
    )
    assert shape.max_words == 500


def test_an_implausible_cap_is_a_misread_and_the_default_target_applies() -> None:
    """Fix round 3, finding 1. All three readings agree on a 30-word cap --
    no disagreement for corroboration to catch -- but no real programme
    states a cap this small (_IMPLAUSIBLE_CAP, grounded in the 119-rule
    research catalogue). Below the band it is treated as a misread digit,
    not a requirement: the cap is dropped and the default target applies,
    rather than blocking every letter for this programme with nobody to see
    why."""
    shape = _decide(
        _line("The letter must not exceed 30 words."),
        _sample(length_measure="words", length_bound="maximum", length_number=30),
        _sample(length_measure="words", length_bound="maximum", length_number=30),
        _sample(length_measure="words", length_bound="maximum", length_number=30),
    )
    assert shape.max_words is None


def test_the_implausible_cap_band_does_not_touch_floors() -> None:
    """Fix round 3, finding 1: the plausibility band applies to CAPS only.
    A floor this small is harmless -- it can only ask for a longer letter,
    never make the requirement unsatisfiable -- so a genuine 10-word floor
    all three readings agree on is kept exactly as before."""
    shape = _decide(
        _line("The letter must be at least 10 words."),
        _sample(length_measure="words", length_bound="minimum", length_number=10),
        _sample(length_measure="words", length_bound="minimum", length_number=10),
        _sample(length_measure="words", length_bound="minimum", length_number=10),
    )
    assert shape.min_words == 10


def test_an_implausible_max_cap_is_a_misread_and_the_default_target_applies() -> None:
    """Fix round 1, finding 2. `letter_max_pages` is a `DecimalField(4, 1)`
    (ceiling 999.9), and `LetterVerdict.length_number` allows up to 1,000,000 for
    every measure -- so an unguarded page cap above the column's ceiling raises
    `DataError` inside `read_and_derive`'s one transaction and rolls back the
    whole read, statements and snapshot included. No real programme states a
    5,000-page cap; `_IMPLAUSIBLE_MAX` rejects it the same way `_IMPLAUSIBLE_CAP`
    rejects an implausibly small one, and the default target applies instead."""
    shape = _decide(
        _line("The letter must not exceed 5000 pages."),
        _sample(length_measure="pages", length_bound="maximum", length_number=5000),
        _sample(length_measure="pages", length_bound="maximum", length_number=5000),
        _sample(length_measure="pages", length_bound="maximum", length_number=5000),
    )
    assert shape.max_pages is None


def test_an_implausible_max_floor_is_a_misread_and_the_default_target_applies() -> None:
    """Fix round 1, finding 2. Unlike `_IMPLAUSIBLE_CAP`, `_IMPLAUSIBLE_MAX`
    applies to FLOORS too: a too-small floor is harmless, but an absurd one
    (here 1,000,000 words -- `LetterVerdict.length_number`'s own ceiling) blocks
    every letter for the programme, which is exactly what an unguarded floor
    would do."""
    shape = _decide(
        _line("The letter must be at least 1000000 words."),
        _sample(length_measure="words", length_bound="minimum", length_number=1_000_000),
        _sample(length_measure="words", length_bound="minimum", length_number=1_000_000),
        _sample(length_measure="words", length_bound="minimum", length_number=1_000_000),
    )
    assert shape.min_words is None


def test_a_normal_page_cap_still_works_under_the_implausible_max_band() -> None:
    """Fix round 1, finding 2: the new upper band must not catch an ordinary
    cap. Two pages is the shape used throughout this repo's own examples
    (spec, letter-shape-rules.csv) and stays well inside [_IMPLAUSIBLE_CAP,
    _IMPLAUSIBLE_MAX] for pages."""
    shape = _decide(
        _line("The letter must not exceed 2 pages."),
        _sample(length_measure="pages", length_bound="maximum", length_number=2),
        _sample(length_measure="pages", length_bound="maximum", length_number=2),
        _sample(length_measure="pages", length_bound="maximum", length_number=2),
    )
    assert shape.max_pages == 2


def test_the_none_votes_still_veto_a_lone_cap_reading() -> None:
    """Pins the fix round 2 escape hatch's own scope, so a future change to
    the corroboration gate (or to the implausible-cap band added this round)
    cannot silently widen it: the hatch applies only when EVERY reading
    agrees the line states some length, so a reading that abstains with
    "none" is still a veto over a lone reading's cap.

    Fix round 4, finding 2: this used to read a cap of 12, which round 3's
    plausibility band (_IMPLAUSIBLE_CAP["words"] == 50) rejects on its own
    regardless of what the corroboration hatch does -- with corroboration
    disabled outright, this test still passed, pinning nothing. 60 is
    deliberately ABOVE the band, so the hatch alone decides the outcome and
    this test fails if the hatch is ever widened, rather than being rescued
    by the band."""
    shape = _decide(
        _line("Room 60, Building A."),
        _sample(length_measure="words", length_bound="maximum", length_number=60),
        _sample(),
        _sample(),
    )
    assert shape.max_words is None


def test_two_dropped_readings_do_not_let_a_lone_survivor_set_a_cap() -> None:
    """Fix round 4, finding 1: the corroboration hatch compared `count` and
    `none_count` against `verdicts`, which is only what SURVIVED
    `_verdicts_for` for this line -- not the three raw samples.
    `_verdicts_for` drops a whole sample's verdict for a line when that
    sample returned two or more verdicts for it (a reading that failed to
    settle). When two of three samples are dropped that way, exactly one
    verdict survives, `none_count` is trivially zero because nothing is left
    to disagree with, and the hatch fired -- treating a lone survivor as
    corroboration. A lone survivor is not corroboration."""
    line = _line("The letter must not exceed 60 words.")
    unsettled = Derivations(
        letters=(
            LetterVerdict(
                statement_index=0, subject="applicant_letter",
                length_measure="words", length_bound="maximum", length_number=60,
            ),
            LetterVerdict(
                statement_index=0, subject="applicant_letter",
                length_measure="characters", length_bound="maximum", length_number=1500,
            ),
        )
    )
    shape = decide_letter_shape(
        (line,),
        [
            unsettled,
            unsettled,
            _sample(length_measure="words", length_bound="maximum", length_number=60),
        ],
        source_url="https://x.example/p",
    )
    assert shape.max_words is None


@pytest.mark.django_db
def test_a_derived_shape_lands_on_the_prompt_and_round_trips(program) -> None:
    shape = LetterShape(
        document_required="REQUIRED", max_words=500, min_words=300, form="FORMAL_LETTER",
        naming="FORBIDDEN", font_family="Times New Roman", font_min_pt=12, line_spacing=1.5,
        margins_cm=2.0, file_bundle="SINGLE_PDF_ALL", handwritten=True, signed_declaration=True,
        sources={"max_words": {"text": "at most 500 words", "source_url": "https://x.example/p"}},
        written_requirements=({"text": "Write in the third person.", "source_url": "u"},),
        student_actions=({"text": "Sign it in ink.", "source_url": "u"},),
        track="research", portfolio_led=True,
    )

    prompt = apply_derived_shape(program, "2027", shape, source_url="https://x.example/p")

    assert prompt.letter_max_words == 500 and prompt.letter_naming == "FORBIDDEN"
    assert prompt.letter_shape_sources["max_words"]["text"] == "at most 500 words"
    program.refresh_from_db()
    assert program.academic_track == "research" and program.portfolio_led is True
    assert shape_from_prompt(prompt) == shape


@pytest.mark.django_db
def test_a_program_write_matching_no_rows_raises_catalog_write_blocked(
    program, monkeypatch
) -> None:
    """Fix round 1, finding 4. `funding_program` carries RLS
    (`catalog_ingestion_write` only -- see CLAUDE.md's RLS section), so a write
    under the runtime role matches zero rows and returns cleanly: a write that
    looks like success and silently did nothing. The bare
    `Program.objects.filter(id=...).update(**changed)` this function used to
    call ignored that row count; this pins the row-count check duplicated from
    `derive.py::_write_program` (see that block's own comment for why it is
    duplicated rather than imported -- derive.py already imports
    `apply_derived_shape` from this module, so the reverse import is circular)."""

    class _ZeroRowQuerySet:
        def update(self, **kwargs: object) -> int:
            return 0

    real_filter = Program.objects.filter

    def _filter(*args, **kwargs):
        if kwargs == {"id": program.id}:
            return _ZeroRowQuerySet()
        return real_filter(*args, **kwargs)

    monkeypatch.setattr(Program.objects, "filter", _filter)

    with pytest.raises(CatalogWriteBlocked):
        apply_derived_shape(
            program, "2027", LetterShape(track="research"), source_url="https://x.example/p"
        )


@pytest.mark.django_db
def test_a_verified_prompt_is_never_overwritten_by_a_page_read(program) -> None:
    """The ladder's precedence: a hand-verified row beats everything (spec §4)."""
    ApplicationPrompt.objects.create(
        programme=program, cycle="2027", confidence=1.0,
        source=ApplicationPrompt.Source.VERIFIED,
        funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        document_language="en", letter_max_words=900,
    )

    prompt = apply_derived_shape(
        program, "2027", LetterShape(max_words=500), source_url="https://x.example/p"
    )

    assert prompt.letter_max_words == 900


@pytest.mark.django_db
def test_a_verification_committed_between_the_two_reads_is_not_overwritten(
    program, monkeypatch
) -> None:
    """Fix round 1, finding 3. `apply_derived_shape` reads the row twice: once
    filtered on `source=VERIFIED` (the ladder short-circuit), once not (to find
    the row to update). A human verification committing in the gap between the
    two reads is invisible to the first (which already ran and found nothing)
    but present for the second -- and the second branch used to setattr the
    derived shape onto whatever it found there, VERIFIED or not. Simulated here
    by making the first `.filter(...)` call return empty regardless of DB state
    (standing in for "ran before the verification landed") and creating the
    VERIFIED row as that call's side effect, so the second, real `.filter(...)`
    call finds it exactly as it would in the live race."""
    real_filter = ApplicationPrompt.objects.filter
    calls = {"n": 0}

    def _filter(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            ApplicationPrompt.objects.create(
                programme=program, cycle="2027", confidence=1.0,
                source=ApplicationPrompt.Source.VERIFIED,
                funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
                structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
                document_language="en", letter_max_words=900,
            )
            return ApplicationPrompt.objects.none()
        return real_filter(*args, **kwargs)

    monkeypatch.setattr(ApplicationPrompt.objects, "filter", _filter)

    prompt = apply_derived_shape(
        program, "2027", LetterShape(max_words=500), source_url="https://x.example/p"
    )

    assert prompt.letter_max_words == 900


@pytest.mark.django_db
def test_silence_leaves_the_track_blank_and_blank_resolves_as_taught(program) -> None:
    apply_derived_shape(program, "2027", LetterShape(), source_url="https://x.example/p")
    program.refresh_from_db()
    assert program.academic_track == ""


def test_a_cap_written_with_a_thousands_separator_verifies_against_the_real_number() -> None:
    """PR review: "no more than 1,500 words" read as the numbers 1 and 500.

    So the true cap was dropped as unverifiable, and a reading that misread it
    as 500 verified and stood -- a SMALLER cap than the page states, which is
    the direction that ships a letter the portal rejects.
    """
    line = _line("The letter is no more than 1,500 words.")
    shape = _decide(
        line,
        _sample(length_measure="words", length_bound="maximum", length_number=1500),
        _sample(length_measure="words", length_bound="maximum", length_number=1500),
    )
    assert shape.max_words == 1500

    misread = _decide(
        line,
        _sample(length_measure="words", length_bound="maximum", length_number=500),
        _sample(length_measure="words", length_bound="maximum", length_number=500),
    )
    assert misread.max_words is None


def test_a_decimal_comma_is_not_a_thousands_separator() -> None:
    """"1,5 Seiten" must never verify as 15."""
    shape = _decide(
        _line("Die Begründung umfasst höchstens 1,5 Seiten."),
        _sample(length_measure="pages", length_bound="maximum", length_number=15),
        _sample(length_measure="pages", length_bound="maximum", length_number=15),
    )
    assert shape.max_pages is None


def test_a_floor_no_column_carries_is_dropped_rather_than_cited() -> None:
    """PR review: a character or page MINIMUM wrote sources["min_chars"].

    LetterShape has only `min_words`, so the bound itself was silently lost
    while its citation survived -- and the requirements pane then showed the
    student that sentence as enforced.
    """
    shape = _decide(
        _line("The letter is at least 3000 characters."),
        _sample(length_measure="characters", length_bound="minimum", length_number=3000),
    )
    assert shape.min_words is None
    assert "min_chars" not in shape.sources


@pytest.mark.django_db
def test_a_stated_letter_language_reaches_the_prompt_and_round_trips(program) -> None:
    """Addendum §6.4: the `language` operation writes document_language."""
    shape = LetterShape(
        max_words=500, document_language="de",
        sources={"document_language": {"text": "auf Deutsch", "source_url": "u"}},
    )
    prompt = apply_derived_shape(program, "2027", shape, source_url="https://x.example/p")
    assert prompt.document_language == "de"
    assert shape_from_prompt(prompt) == shape


@pytest.mark.django_db
def test_a_grammar_reread_that_stops_stating_the_language_resets_to_english(program) -> None:
    """Fix round 2, finding 4: resetting to "" broke check_language_mismatch
    (content.language="en" != document_language="" is a permanent mismatch)
    and LetterContent(language="") (min_length=2 -- a crash). The reset value
    is _FALLBACK_LANGUAGE, the same "en" prompt_resolution falls back to and a
    new row starts in, so a page that stops stating a language reads exactly
    like a page that never stated one."""
    apply_derived_shape(
        program, "2027",
        LetterShape(
            document_language="de",
            sources={"document_language": {"text": "Auf Deutsch.", "source_url": "u"}},
        ),
        source_url="https://x.example/p",
        reads_language=True,
    )
    prompt = apply_derived_shape(
        program, "2027", LetterShape(max_words=500), source_url="https://x.example/p",
        reads_language=True,
    )
    assert prompt.document_language == "en"
    assert shape_from_prompt(prompt).document_language == ""
    content = LetterContent(
        language="en",
        units=(LetterUnit(archetype="OPENING", text="Dear admissions committee."),),
    )
    assert check_language_mismatch(content, document_language=prompt.document_language) == ()


@pytest.mark.django_db
def test_a_frontier_reread_never_resets_a_language_the_grammar_stated(program) -> None:
    """Fix round 2, finding 4(b): the frontier path (decide_letter_shape ->
    apply_derived_shape) never sets document_language, so without the
    reads_language guard its every re-read would wipe out a language the
    grammar path had written, although the frontier never reads language.
    The frontier caller (derive.py:1352) passes no reads_language, so this
    call -- standing in for it -- must default to False."""
    apply_derived_shape(
        program, "2027",
        LetterShape(
            document_language="de",
            sources={"document_language": {"text": "Auf Deutsch.", "source_url": "u"}},
        ),
        source_url="https://x.example/p",
        reads_language=True,
    )
    prompt = apply_derived_shape(
        program, "2027", LetterShape(max_words=500), source_url="https://x.example/p",
    )
    assert prompt.document_language == "de"


@pytest.mark.django_db
def test_a_page_stating_no_language_leaves_the_prompts_language_alone(program) -> None:
    ApplicationPrompt.objects.create(
        programme=program, cycle="2027", confidence=0.0,
        source=ApplicationPrompt.Source.EXTRACTED,
        funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        document_language="fr",
    )
    prompt = apply_derived_shape(
        program, "2027", LetterShape(max_words=500), source_url="https://x.example/p"
    )
    assert prompt.document_language == "fr"
    assert shape_from_prompt(prompt).document_language == ""


@pytest.mark.django_db
def test_a_new_prompt_starts_in_the_stated_language(program) -> None:
    prompt = apply_derived_shape(
        program, "2027", LetterShape(document_language="pt"), source_url="https://x.example/p"
    )
    assert prompt.document_language == "pt"


@pytest.mark.django_db
def test_a_character_floor_reaches_the_prompt(program) -> None:
    prompt = apply_derived_shape(
        program, "2027", LetterShape(min_chars=2800), source_url="https://x.example/p"
    )
    assert prompt.letter_min_chars == 2800
