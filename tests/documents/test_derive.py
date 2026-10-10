import csv
import math
import pathlib
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.conf import settings
from django.utils import timezone
from pydantic import ValidationError

from apps.documents.constraints import _INCLUDE_TARGETS, _SECTIONS, resolve_rules
from apps.documents.derive import (
    _CLAUDE_MAX_TOKENS,
    _DERIVE_MAX_OUTPUT_TOKENS,
    _PHRASINGS,
    _SAMPLES,
    Candidate,
    DerivationFailure,
    Derivations,
    Derived,
    Directive,
    FormatVerdict,
    LetterVerdict,
    Outcome,
    _judge,
    _write_program,
    candidates,
    decide,
    derive_page_rules,
    outcomes,
)
from apps.documents.program_rules import read_and_derive
from apps.documents.render import render_cv_with_warnings
from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    ExperienceEntry,
    PersonalInformation,
    ResearchEntry,
)
from apps.funding.models import (
    ApplicationPrompt,
    CatalogWriteBlocked,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
    ProgramStatement,
)
from apps.research.egress import FetchResult, SourceBlocked
from apps.research.extraction import privacy_safe_identifier
from apps.research.reader import _CONTROL_PATH, _READS, Statement, Statements

pytestmark = pytest.mark.django_db


def _snapshot() -> OfficialSourceSnapshot:
    source = OfficialSource.objects.create(
        canonical_url=f"https://official.example/{uuid4()}",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    return OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key=f"official-sources/{uuid4()}",
        s3_version_id="1",
        sha256="0" * 64,
        final_url=source.canonical_url,
        redirect_chain=[],
        retrieved_at=timezone.now(),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=1,
    )


def _say(program, text, kind="FORMAT", requirement="REQUIRED"):
    return ProgramStatement.objects.create(
        program=program, snapshot=_snapshot(), kind=kind,
        requirement=requirement, text=text, label=text[:20],
    )


def test_write_program_raises_when_the_update_matches_no_rows():
    """A catalog table carries a SELECT-only RLS policy for the runtime role,
    so an UPDATE from that role matches zero rows and returns cleanly -- a
    write that looks like success and did nothing. _write_program's rowcount
    check is what turns that silent failure into CatalogWriteBlocked. A
    nonexistent Program id is the simplest way to make the rowcount zero
    without a second, RLS-restricted database role."""
    with pytest.raises(CatalogWriteBlocked):
        _write_program(uuid4(), cv_format_requirement=Program.CVFormatRequirement.EUROPASS_REQUIRED)


def test_a_derived_key_outside_the_allowed_set_is_refused_by_the_schema():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Derived(statement_index=0, key="required_fields", value=["x"])


@dataclass
class FakeResponse:
    output_parsed: object
    id: str = "resp_derive_1"
    usage: object = field(
        default_factory=lambda: SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2)
    )
    output: list[object] | None = None
    #: The Anthropic side of the same fake: messages.parse returns
    #: parsed_output and a stop_reason, so one script can answer both clients
    #: in call order.
    stop_reason: str = "end_turn"

    @property
    def parsed_output(self) -> object:
        return self.output_parsed


class _MemoryStore:
    def __init__(self) -> None:
        self.objects: list[tuple[str, bytes]] = []

    def put(self, key: str, body: bytes) -> str:
        self.objects.append((key, body))
        return "v1"


class _ScriptedJudge:
    """One response per call, in order. Length comes from _SAMPLES -- or from
    _READS + _SAMPLES when the script also stands in for the page reads that
    precede the judge calls (read_and_derive's parser). Passed as both
    `parser` and `claude`, it answers the two OpenAI readings and then the
    Claude one, in the order _judge asks them."""

    def __init__(self, *responses: object) -> None:
        self.responses = [
            r if isinstance(r, FakeResponse) else FakeResponse(output_parsed=r) for r in responses
        ]
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        return self.responses.pop(0)


_BODY = (
    b"<html><body><main><h2>Required documents</h2>"
    b"<ul><li>Your CV must not exceed two pages.</li>"
    b"<li>Please submit your CV in Europass format.</li>"
    b"<li>State your ECTS credits.</li></ul></main></body></html>"
)
# candidates() over _BODY: 0 = pages and 1 = europass are found by the
# page-scan (they carry a CV/europass term); 2 = ects has neither, so it only
# reaches candidates() via the statement _READ quotes below. readable_text
# renders each <li> as "- text", but candidates() strips that list marker
# before it becomes rule_text or a dedup key, so all three land marker-free
# and in this order. Verified against candidates() directly.
_READ = Statements(statements=(
    Statement(text="Your CV must not exceed two pages.", kind="DOCUMENT",
              requirement="REQUIRED", label="CV length"),
    Statement(text="State your ECTS credits.", kind="DOCUMENT",
              requirement="REQUIRED", label="ECTS credits"),
))
_AGREE = Derivations(
    formats=(FormatVerdict(statement_index=1, value="required"),),
    rules=(Derived(statement_index=0, key="max_pages", value=2),),
    directives=(Directive(statement_index=2, action="include",
                          target="education.ects_credits", about_whom="applicant"),),
    # The letter question asks for a verdict on every line, same as
    # directives -- none of these three lines is about the letter, so every
    # verdict is the "says nothing" default (subject="other").
    letters=tuple(LetterVerdict(statement_index=i, subject="other") for i in range(3)),
)


def _source():
    # get_or_create, not create: _read() calls this fresh every time, and a
    # test that reads the same programme's page twice (an unchanged-page
    # check) must see the SAME source both times -- read_program_page's
    # unchanged check compares snapshot.source_id, and two rows sharing this
    # canonical_url would violate its uniqueness besides.
    return OfficialSource.objects.get_or_create(
        canonical_url="https://official.example/msc",
        defaults={"publisher": "Official University", "source_type": OfficialSource.Type.PROGRAM},
    )[0]


def _serving(body: bytes):
    """A host that serves `body` at any real path and refuses a missing one.

    The refusal matters: the reader asks every host for a path nothing serves
    and compares the answer against the page, so a double that returns the
    page for ANY url is describing a host whose every page is its not-found
    page -- and the read is correctly recorded SOFT_404 instead of derived.
    """

    def _retrieve(url: str) -> FetchResult:
        if _CONTROL_PATH in url:
            raise SourceBlocked("source returned HTTP 404")
        return FetchResult(url, (), "text/html", body)

    return _retrieve


def _read(program, parser, body=_BODY):
    return read_and_derive(
        program=program, source=_source(), store=_MemoryStore(), parser=parser,
        claude=parser, admissions_cycle="2027",
        retrieve=_serving(body),
    )


def test_one_read_switches_the_format_writes_the_rule_and_the_directive(program_factory):
    program = program_factory()
    parser = _ScriptedJudge(
        *([FakeResponse(output_parsed=_READ)] * _READS),
        *(FakeResponse(output_parsed=j) for j in [_AGREE] * _SAMPLES),
    )

    result = _read(program, parser)

    assert result.wrote and len(parser.calls) == _READS + _SAMPLES
    program.refresh_from_db()
    assert (program.cv_format_requirement, program.cv_format_confidence) == (
        "europass_required", "EXTRACTED",
    )
    assert [(r["key"], r["value"], r["rule_text"]) for r in program.cv_constraints] == [
        ("max_pages", 2, "Your CV must not exceed two pages."),
    ]
    assert [(d["action"], d["target"], d["rule_text"]) for d in program.cv_directives] == [
        ("include", "education.ects_credits", "State your ECTS credits."),
    ]


def test_a_split_reading_abstains_and_the_student_sees_the_sentence(program_factory):
    program = program_factory()
    dissent = Derivations(
        formats=(FormatVerdict(statement_index=1, value="not_required"),),
        rules=_AGREE.rules, directives=_AGREE.directives, letters=_AGREE.letters,
    )
    parser = _ScriptedJudge(
        *([FakeResponse(output_parsed=_READ)] * _READS),
        *(FakeResponse(output_parsed=j) for j in (_AGREE, _AGREE, dissent)),
    )

    _read(program, parser)

    program.refresh_from_db()
    assert (program.cv_format_requirement, program.cv_format_confidence) == ("any", "UNDECIDED")
    assert [(r["key"], r["value"], r["rule_text"]) for r in program.cv_constraints] == [
        ("undecided", "cv_format", "Please submit your CV in Europass format."),
    ]
    assert program.cv_directives == []


def test_a_page_the_statement_read_could_not_quote_is_still_judged(program_factory):
    """Recall no longer depends on which sentences the read selected: the
    read returns nothing usable, the page still changed, the judge still runs."""
    program = program_factory()
    parser = _ScriptedJudge(
        *([FakeResponse(output_parsed=Statements())] * _READS),
        *(FakeResponse(output_parsed=j) for j in [_AGREE] * _SAMPLES),
    )

    result = _read(program, parser)

    assert not result.wrote and len(parser.calls) == _READS + _SAMPLES
    program.refresh_from_db()
    assert program.cv_format_requirement == "europass_required"


def test_an_unchanged_page_derives_nothing_again(program_factory):
    program = program_factory()
    parser = _ScriptedJudge(
        *([FakeResponse(output_parsed=_READ)] * _READS),
        *(FakeResponse(output_parsed=j) for j in [_AGREE] * _SAMPLES),
    )
    _read(program, parser)
    second = _read(program, parser)
    assert not second.model_called and len(parser.calls) == _READS + _SAMPLES


def test_an_unreadable_page_derives_nothing(program_factory):
    program = program_factory(
        cv_format_requirement="europass_required", cv_format_confidence="EXTRACTED",
    )
    shell = b"<html><body><p>Loading</p><script>" + b"x" * 60_000 + b"</script></body></html>"
    parser = _ScriptedJudge(
        *([FakeResponse(output_parsed=_READ)] * _READS),
        *(FakeResponse(output_parsed=j) for j in [_AGREE] * _SAMPLES),
    )

    result = _read(program, parser, body=shell)

    assert result.snapshot is not None
    assert result.snapshot.readability == OfficialSourceSnapshot.Readability.SHELL
    assert parser.calls == []
    program.refresh_from_db()
    assert program.cv_format_requirement == "europass_required"


#: A German sentence with no English CV/letter vocabulary at all, so it can only
#: become a letter candidate through `letter_terms.TERMS["de"].document` -- and
#: `detect_language` can only pick "de" by scoring stopwords ("das", "und") against
#: the raw text, since no `<html lang>` attribute is supplied here (page_language=
#: ""). This is the case fix round 1's finding 5 names: replacing
#: `detect_language(page_text, html_lang=page_language)` with the bare
#: `page_language` attribute passes the rest of the suite untouched because no
#: other fixture page states a letter rule in a non-English sentence.
_GERMAN_LETTER_PAGE = (
    "Bitte beachten Sie: Das Motivationsschreiben darf maximal 2 Seiten umfassen "
    "und muss unterschrieben sein."
)
_GERMAN_AGREE = Derivations(
    # Not a real CV verdict -- present only so _with_one_retry's `_touches_cv`
    # check sees this one line as judged and does not spend a second call
    # retrying it. The candidate's own `cv` flag is False (no CV/europass term
    # in the German sentence), so decide()'s CV path never looks at this.
    formats=(FormatVerdict(statement_index=0, value="none"),),
    letters=(
        LetterVerdict(
            statement_index=0, subject="applicant_letter",
            length_measure="pages", length_bound="maximum", length_number=2,
        ),
    ),
)


def test_derive_page_rules_resolves_a_non_english_page_via_the_language_detector(
    program_factory,
):
    """Pins fix round 1's finding 5: `derive_page_rules` must call
    `detect_language`, not trust the raw `page_language` argument. Verified by
    temporarily replacing `language = detect_language(...)` with
    `language = page_language` in derive.py: this test FAILS (max_pages stays
    unset, because "" never yields German candidates), and passes again once the
    call is restored -- see fix round 1's report for the exact before/after."""
    program = program_factory()
    parser = _ScriptedJudge(*([FakeResponse(output_parsed=_GERMAN_AGREE)] * _SAMPLES))

    derive_page_rules(
        program, parser=parser, claude=parser, page_text=_GERMAN_LETTER_PAGE,
        snapshot=_snapshot(), admissions_cycle="2027", page_language="",
    )

    prompt = ApplicationPrompt.objects.get(programme=program, cycle="2027")
    assert prompt.letter_max_pages == 2


def test_a_hand_verified_format_is_never_overwritten_but_rules_still_land(program_factory):
    program = program_factory(
        cv_format_requirement="funder_template", cv_format_confidence="VERIFIED",
        cv_format_verified_for_cycle="2027/28",
    )
    parser = _ScriptedJudge(
        *([FakeResponse(output_parsed=_READ)] * _READS),
        *(FakeResponse(output_parsed=j) for j in [_AGREE] * _SAMPLES),
    )
    _read(program, parser)
    program.refresh_from_db()
    assert (program.cv_format_requirement, program.cv_format_confidence) == (
        "funder_template", "VERIFIED",
    )
    assert [r["key"] for r in program.cv_constraints] == ["max_pages"]


def test_a_page_with_no_cv_line_makes_no_judge_call(program_factory):
    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 3,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": "",
    }])
    fees = (
        b"<html><body><main><h2>Fees</h2>"
        b"<p>Tuition is 1,500 EUR per semester.</p></main></body></html>"
    )
    parser = _ScriptedJudge(
        *([FakeResponse(output_parsed=Statements())] * _READS),
        *(FakeResponse(output_parsed=j) for j in [_AGREE] * _SAMPLES),
    )

    _read(program, parser, body=fees)

    assert len(parser.calls) == _READS
    program.refresh_from_db()
    # NO_CV_FOUND, not EXTRACTED. Both leave cv_format_requirement `any`, and
    # until this split they were the same stored state -- so "we read the page
    # and it asks for a CV with no format rule" and "we read the page and
    # nothing on it looked like a CV requirement at all" were indistinguishable
    # afterwards. The second is the one that may be our own failure (a language
    # our finder does not know), and it has to be visible to be measured.
    assert (program.cv_format_requirement, program.cv_format_confidence) == ("any", "NO_CV_FOUND")
    assert program.cv_constraints == [] and program.cv_directives == []


def test_total_refusal_rolls_the_statements_back_with_the_rules(program_factory):
    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 3,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": "",
    }])
    stale = _say(program, "A stale sentence from a previous, different read.", kind="DOCUMENT")
    before = set(ProgramStatement.objects.filter(program=program).values_list("id", flat=True))
    parser = _ScriptedJudge(
        *([FakeResponse(output_parsed=_READ)] * _READS),
        # Every reading refuses its first ask and its one retry.
        *(FakeResponse(output_parsed=j) for j in [None] * (2 * _SAMPLES)),
    )

    with pytest.raises(DerivationFailure):
        _read(program, parser)

    program.refresh_from_db()
    after = set(ProgramStatement.objects.filter(program=program).values_list("id", flat=True))
    assert after == before
    assert ProgramStatement.objects.get(id=stale.id).text == stale.text
    assert program.cv_constraints[0]["value"] == 3


def test_the_page_rule_reaches_a_render_as_an_advisory_violation_with_the_sentence(program_factory):
    """STANDARD plus the page's own rules on top: the whole point, end to end."""
    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0", "key": "max_pages", "value": 1,
        "enforcement": "ADVISORY_HIGH_RISK",
        "rule_text": "Your CV must not exceed one page.",
        "source_url": "https://official.example/msc",
    }])
    content = CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
        education=(EducationEntry(degree_as_awarded="BSc",
                                  institution_original="Example University",
                                  city="Berlin", country="DE", start_date="2020-09-01"),),
        experience=tuple(
            ExperienceEntry(employer=f"Employer {i}", title=f"Research Assistant {i}",
                            city="Berlin", country="DE",
                            start_date=date(2015 + i % 9, 1, 1), end_date=date(2016 + i % 9, 1, 1),
                            bullets=("Ran the thing and wrote it up.",))
            for i in range(14)
        ),
        research=(), publications=(), awards=(), skills=(), languages=(),
        summary=None, document_language="en",
    )
    rules = resolve_rules(program, None, content=content)
    assert [r.rule_id for r in rules if r.key == "max_pages"] == ["PAGE-0"]

    artifact, violations = render_cv_with_warnings(content, variant="STANDARD", constraints=rules)

    assert artifact.page_count and artifact.page_count > 1
    page_rule = [v for v in violations if v.rule.rule_id == "PAGE-0"]
    assert len(page_rule) == 1
    assert page_rule[0].rule.enforcement == "ADVISORY_HIGH_RISK"
    assert page_rule[0].rule.rule_text == "Your CV must not exceed one page."


# --- candidates: what the model is asked about, found by code ---------------


def test_every_europass_line_is_a_candidate_even_without_a_cv_word():
    """i-MESC's real mandate is "Please use the Europass model." -- no CV word.
    A CV-term filter scanned past it into a silent `any`."""
    page = "# Application\nPlease use the Europass model.\nUpload your passport."
    found = candidates(page, ())
    assert [c.text for c in found] == ["Please use the Europass model."]
    assert found[0].europass and found[0].heading == "Application"


def test_a_cv_term_line_is_a_candidate_and_carries_its_nearest_heading():
    page = (
        "# Documents\n- Passport photo\n## Curriculum vitae\n"
        "- maximum two pages\n- Your CV must be in English."
    )
    found = candidates(page, ())
    assert [(c.text, c.heading) for c in found] == [
        # The heading itself carries a CV term, so it is judged too (under the
        # heading above it); the model answers `none` for it.
        ("Curriculum vitae", "Documents"),
        ("Your CV must be in English.", "Curriculum vitae"),
    ]


def test_a_heading_that_states_the_requirement_is_a_candidate():
    page = "# Documents\n## Europass CV required\n- Passport photo"
    found = candidates(page, ())
    assert [(c.text, c.heading, c.europass) for c in found] == [
        ("Europass CV required", "Documents", True)
    ]


def test_a_prose_line_starting_with_a_hash_is_not_a_heading():
    page = "#1 priority: your CV must be in English."
    found = candidates(page, ())
    assert [c.text for c in found] == ["#1 priority: your CV must be in English."]
    assert found[0].heading == ""


def test_a_statement_the_vocabulary_missed_is_still_a_candidate():
    """The second recall path: the statement read quoted a Turkish CV line
    that _CV_TERMS does not know."""
    page = "# Belgeler\n- Özgeçmiş en fazla iki sayfa olmalıdır.\n- Pasaport fotokopisi"
    found = candidates(page, ("Özgeçmiş en fazla iki sayfa olmalıdır.",))
    assert [c.text for c in found] == ["Özgeçmiş en fazla iki sayfa olmalıdır."]
    assert not found[0].europass


def test_a_statement_already_found_on_the_page_is_not_listed_twice():
    page = "Your CV must be in English."
    found = candidates(page, ("your cv must be in english.",))
    assert len(found) == 1


def test_a_bulleted_line_loses_its_marker_and_dedups_against_the_quoted_statement():
    """readable_text renders <li> as "- text". The marker is structure for the
    model's read, not part of the sentence: rule_text must not carry it, and a
    statement the read quoted without it is the same candidate."""
    page = "# Documents\n- Your CV must be in English.\n- A passport photo"
    found = candidates(page, ("Your CV must be in English.",))
    assert [c.text for c in found] == ["Your CV must be in English."]


def test_a_cv_line_about_somebody_else_is_a_candidate_and_is_marked_as_theirs():
    page = "Short CV (max. 2 pages) from this academic supervisor.\nYour CV must be in English."
    theirs, mine = candidates(page, ())
    assert theirs.third_party and not mine.third_party


def test_a_page_with_no_cv_or_europass_line_has_no_candidates():
    assert candidates("# Fees\nTuition is 1,500 EUR per semester.", ()) == ()


# --- the closed question ------------------------------------------------------


def test_every_include_target_is_a_real_optional_field_of_the_cv_schema():
    """The target list is closed and pinned to CVContent: a directive can
    only ever name a field the document actually has."""
    models = {"education": EducationEntry, "experience": ExperienceEntry,
              "research": ResearchEntry, "personal": PersonalInformation}
    for target in _INCLUDE_TARGETS:
        section, field = target.split(".")
        assert field in models[section].model_fields, target
    for section in _SECTIONS:
        assert section in CVContent.model_fields, section


@pytest.mark.parametrize(
    "payload",
    [
        {"statement_index": 0, "action": "include", "target": "education.gpa"},
        {"statement_index": 0, "action": "include"},
        {"statement_index": 0, "action": "order", "target": "education"},
        {"statement_index": 0, "action": "order", "target": "education.ects_credits",
         "value": "chronological"},
        {"statement_index": 0, "action": "emphasise", "target": "personal.date_of_birth"},
        {"statement_index": 0, "action": "exclude", "target": "personal.full_name"},
        {"statement_index": 0, "action": "unapplied", "target": "education"},
    ],
)
def test_a_malformed_directive_is_rejected_by_the_schema(payload):
    # about_whom is supplied so each payload still fails for its own reason
    # and not merely for the missing attribution.
    with pytest.raises(ValidationError):
        Directive.model_validate({"about_whom": "applicant", **payload})


def test_a_well_formed_directive_validates():
    Directive(statement_index=1, action="order", target="education", value="chronological",
              about_whom="applicant")
    Directive(statement_index=2, action="include", target="education.ects_credits",
              about_whom="applicant")
    Directive(statement_index=3, action="emphasise", target="experience", about_whom="applicant")
    Directive(statement_index=4, action="unapplied", about_whom="applicant")
    Directive(statement_index=5, action="none", about_whom="applicant")
    FormatVerdict(statement_index=0, value="other_template")


#: An answer that judged the one line in a "0 | ..." listing, for BOTH
#: documents. An empty Derivations() judged nothing, which the judge now
#: treats as thin and asks again -- and since Fix round 1, finding 2, "judged"
#: means _touches_cv AND _touches_letter, because the letter question asks
#: for a verdict on every line just as the directive question does. A test
#: meaning "this reading answered" must use this.
_ANSWERED = Derivations(
    directives=(Directive(statement_index=0, action="none", about_whom="applicant"),),
    letters=(LetterVerdict(statement_index=0, subject="other"),),
)


def test_the_judge_asks_three_times_in_three_phrasings_and_two_model_families():
    parser = _ScriptedJudge(*[_ANSWERED for _ in range(_SAMPLES - 1)])
    claude = _ScriptedJudge(_ANSWERED)
    samples = _judge(parser, claude, program_id="p", listing="0 | Your CV must be in English.")
    assert len(samples) == _SAMPLES
    assert len(parser.calls) == _SAMPLES - 1 and len(claude.calls) == 1
    prompts = [c["input"][0]["content"] for c in parser.calls] + [claude.calls[0]["system"]]
    assert len(set(prompts)) == _SAMPLES == len(set(_PHRASINGS))
    for call in parser.calls:
        assert call["store"] is False
        assert call["input"][1]["content"].startswith("DATA")
        assert call["model"] == settings.OPENAI_EXTRACTION_MODEL
        assert call["max_output_tokens"] == _DERIVE_MAX_OUTPUT_TOKENS
        assert call["safety_identifier"] == privacy_safe_identifier("p")
    (call,) = claude.calls
    assert call["messages"] == [{"role": "user", "content": parser.calls[0]["input"][1]["content"]}]
    assert call["model"] == settings.ANTHROPIC_JUDGE_MODEL == "claude-sonnet-5"
    assert call["max_tokens"] == _CLAUDE_MAX_TOKENS
    assert call["output_format"] is Derivations
    assert call["metadata"] == {"user_id": privacy_safe_identifier("p")}


def test_the_claude_budget_stays_inside_the_sdk_non_streaming_ceiling() -> None:
    """The SDK refuses a non-streaming call implying over ten minutes of work.
    Measured 2026-09-19 against the installed version: max_tokens must be at
    most 3600 * max_tokens / 128000 <= 600, i.e. ~21,333. Raising
    _CLAUDE_MAX_TOKENS past that fails at request time, on every real call.
    """
    assert _CLAUDE_MAX_TOKENS * 3600 / 128_000 <= 600


# --- the one retry ----------------------------------------------------------------
#
# Measured live 2026-09-14 under unanimity: what failed the gate was readers
# dropping out -- an off-schema OpenAI answer, a round left with one reading,
# a round whose every row came back unjudged -- not readers disagreeing. Under
# unanimity one missing or thin reading abstains the whole page, so each
# reading gets exactly one more ask.


def test_a_dropped_openai_reading_is_asked_once_more():
    parser = _ScriptedJudge(None, _ANSWERED, _ANSWERED)
    claude = _ScriptedJudge(_ANSWERED)
    samples = _judge(parser, claude, program_id="p", listing="0 | x")
    assert len(samples) == _SAMPLES and len(parser.calls) == _SAMPLES


def test_a_retry_repeats_the_same_phrasing():
    parser = _ScriptedJudge(None, _ANSWERED, _ANSWERED)
    _judge(parser, _ScriptedJudge(_ANSWERED), program_id="p", listing="0 | x")
    first, retry, second = (c["input"][0]["content"] for c in parser.calls)
    assert first == retry != second


def test_a_thin_claude_reading_is_asked_once_more():
    """Parsed and on-schema, but it skipped a line: under unanimity that alone
    leaves the line unjudged for the whole page."""
    two_lines = "0 | a\n1 | b"
    both = Derivations(
        directives=(
            Directive(statement_index=0, action="none", about_whom="applicant"),
            Directive(statement_index=1, action="none", about_whom="applicant"),
        ),
        letters=(
            LetterVerdict(statement_index=0, subject="other"),
            LetterVerdict(statement_index=1, subject="other"),
        ),
    )
    parser = _ScriptedJudge(both, both)
    claude = _ScriptedJudge(_ANSWERED, both)
    samples = _judge(parser, claude, program_id="p", listing=two_lines)
    assert len(claude.calls) == 2 and samples[-1] == both


@pytest.mark.parametrize(
    "answer",
    [
        FakeResponse(output_parsed=None, stop_reason="refusal"),
        # Cut off mid-thought: whatever parsed is not a whole answer.
        FakeResponse(output_parsed=_ANSWERED, stop_reason="max_tokens"),
        FakeResponse(output_parsed={"formats": "not a list"}),
    ],
    ids=["refusal", "truncated", "off-schema"],
)
def test_a_claude_reading_that_fails_twice_is_a_missing_sample_and_is_logged(answer, caplog):
    parser = _ScriptedJudge(*[_ANSWERED for _ in range(_SAMPLES - 1)])
    claude = _ScriptedJudge(answer, answer)
    samples = _judge(parser, claude, program_id="p", listing="0 | x")
    assert len(samples) == _SAMPLES - 1 and len(claude.calls) == 2
    assert "judged by one model family" in caplog.text


def test_a_reading_that_is_thin_twice_keeps_its_retry():
    """Kept, not dropped: outcomes() marks the lines it skipped unjudged, which
    surfaces them; dropping the reading would hide that it answered at all."""
    two_lines = "0 | a\n1 | b"
    both = Derivations(
        directives=(
            Directive(statement_index=0, action="none", about_whom="applicant"),
            Directive(statement_index=1, action="none", about_whom="applicant"),
        ),
        letters=(
            LetterVerdict(statement_index=0, subject="other"),
            LetterVerdict(statement_index=1, subject="other"),
        ),
    )
    parser = _ScriptedJudge(both, both)
    claude = _ScriptedJudge(Derivations(), _ANSWERED)
    samples = _judge(parser, claude, program_id="p", listing=two_lines)
    assert len(samples) == _SAMPLES and samples[-1] == _ANSWERED


def test_a_claude_answer_the_sdk_could_not_validate_twice_is_a_missing_sample():
    class _Raising:
        calls = 0

        def parse(self, **kwargs):
            _Raising.calls += 1
            Derivations.model_validate({"formats": "not a list"})

    parser = _ScriptedJudge(*[_ANSWERED for _ in range(_SAMPLES - 1)])
    assert len(_judge(parser, _Raising(), program_id="p", listing="0 | x")) == _SAMPLES - 1
    assert _Raising.calls == 2


def test_an_openai_answer_the_sdk_could_not_validate_is_retried_not_a_crash():
    """Both SDKs validate inside parse() and raise; neither hands back an
    off-schema payload for parsed_or_none to drop. Measured live 2026-09-14:
    an uncaught ValidationError from one reading crashed the whole judge."""
    class _RaisingOnce(_ScriptedJudge):
        def parse(self, **kwargs):
            if not self.calls:
                self.calls.append(kwargs)
                Derivations.model_validate({"formats": "not a list"})
            return super().parse(**kwargs)

    parser = _RaisingOnce(_ANSWERED, _ANSWERED)
    samples = _judge(parser, _ScriptedJudge(_ANSWERED), program_id="p", listing="0 | x")
    assert len(samples) == _SAMPLES and len(parser.calls) == _SAMPLES


def test_the_real_anthropic_sdk_sends_the_schema_and_parses_the_answer():
    """Offline, through the installed SDK: Derivations must survive the SDK's
    schema transform (unions, Literals, stripped numeric bounds) and a JSON
    answer must come back as a Derivations. Only the transport is fake."""
    anthropic = pytest.importorskip("anthropic")
    import json

    import httpx2

    answer = Derivations(
        formats=(FormatVerdict(statement_index=0, value="required"),),
        letters=(LetterVerdict(statement_index=0, subject="other"),),
    )
    sent: list[dict[str, object]] = []

    def _handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant",
            "model": settings.ANTHROPIC_JUDGE_MODEL, "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "text", "text": answer.model_dump_json()}],
        })

    client = anthropic.Anthropic(
        api_key="test-key-not-a-secret",
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(_handler)),
    )
    parser = _ScriptedJudge(*[_ANSWERED for _ in range(_SAMPLES - 1)])

    samples = _judge(parser, client.messages, program_id="p", listing="0 | Europass CV required.")

    assert samples[-1] == answer
    (body,) = sent
    assert body["model"] == "claude-sonnet-5" and body["max_tokens"] == _CLAUDE_MAX_TOKENS
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["metadata"] == {"user_id": privacy_safe_identifier("p")}
    assert body["messages"][0]["content"].startswith("DATA")


def test_the_judge_raises_when_no_sample_answered():
    parser = _ScriptedJudge(*[None] * (2 * (_SAMPLES - 1)))
    refusal = FakeResponse(output_parsed=None, stop_reason="refusal")
    claude = _ScriptedJudge(refusal, refusal)
    with pytest.raises(DerivationFailure):
        _judge(parser, claude, program_id="p", listing="0 | x")


# --- decide: the action and every rule need all surviving readings -----------

_EU = Candidate(
    text="Please submit your CV in Europass format.", heading="Documents", europass=True
)
_PAGES = Candidate(text="Your CV must not exceed two pages.", heading="Documents", europass=False)
_ECTS = Candidate(text="State your ECTS credits.", heading="CV", europass=False)
_SRC = "https://official.example/msc"


def _sample(formats=(), rules=(), directives=()):
    return Derivations(
        formats=tuple(FormatVerdict(statement_index=i, value=v) for i, v in formats),
        rules=tuple(Derived(statement_index=i, key=k, value=v) for i, k, v in rules),
        directives=tuple(
            Directive(statement_index=d[0], action=d[1], target=d[2], value=d[3],
                      about_whom=d[4] if len(d) > 4 else "applicant")
            for d in directives
        ),
    )


def _unanimous(*, formats=(), rules=(), directives=()):
    return [_sample(formats, rules, directives) for _ in range(_SAMPLES)]


def test_unanimous_required_writes_europass_required():
    d = decide((_EU,), _unanimous(formats=[(0, "required")]), source_url=_SRC)
    assert not d.abstained
    assert (d.format_value, d.confidence) == ("europass_required", "EXTRACTED")
    assert d.rules == () and d.directives == ()


def test_required_and_preferred_agree_on_the_action_and_the_stricter_label_wins():
    samples = [_sample([(0, "required")]), _sample([(0, "preferred")]), _sample([(0, "preferred")])]
    d = decide((_EU,), samples, source_url=_SRC)
    assert not d.abstained and d.format_value == "europass_required"


def test_the_format_action_still_needs_every_reading():
    """Two readings for `required` against one `not_required` abstains -- a
    wrong action here ships the student's name, date of birth and history to
    europa.eu. (Written when advisory rules were a majority; the action never
    was.)"""
    samples = [
        _sample([(0, "required")]), _sample([(0, "required")]), _sample([(0, "not_required")]),
    ]
    d = decide((_EU,), samples, source_url=_SRC)
    assert d.abstained
    assert (d.format_value, d.confidence) == ("any", "UNDECIDED")
    [rule] = d.rules
    assert (rule.key, rule.value, rule.rule_text) == ("undecided", "cv_format", _EU.text)
    assert rule.rule_id == "PAGE-0-cv_format" and rule.enforcement == "ADVISORY_HIGH_RISK"


def test_a_europass_verdict_on_a_line_without_the_word_is_surfaced_not_acted_on():
    """The presence floor: the word must be on the page. Measured on this branch
    before the fix: three unanimous `required` verdicts on this sentence wrote
    europass_required and routed the CV to europa.eu."""
    eu_standard = Candidate(
        text="The CV must follow the EU standard tabular form.", heading="", europass=False
    )
    d = decide(
        (eu_standard,),
        _unanimous(formats=[(0, "required")], directives=[(0, "none", None, None)]),
        source_url=_SRC,
    )
    assert (d.format_value, d.confidence) == ("any", "UNDECIDED")
    assert [(r.key, r.value, r.rule_text) for r in d.rules] == [
        ("undecided", "cv_format", eu_standard.text)
    ]


def test_an_abstention_on_a_page_with_no_europass_line_still_surfaces_the_sentence():
    d = decide((_PAGES,), _unanimous(), source_url=_SRC)  # no sample judged it
    assert d.abstained
    assert [(r.key, r.value, r.rule_text) for r in d.rules] == [
        ("undecided", "unjudged", _PAGES.text)
    ]


def test_two_disputes_on_one_sentence_are_two_rules_with_distinct_ids():
    """_MULTI_KEYS slots surfaced rules by rule_id, so two disputes on one
    sentence collapsed into one warning while `PAGE-0-undecided` was the id."""
    samples = [
        _sample(rules=[(0, "max_pages", 2)],
                directives=[(0, "include", "education.ects_credits", None)]),
        _sample(rules=[(0, "max_pages", 3)], directives=[(0, "unapplied", None, None)]),
        _sample(rules=[(0, "max_pages", 4)], directives=[(0, "emphasise", "experience", None)]),
    ]
    d = decide((_PAGES,), samples, source_url=_SRC)
    assert [(r.key, r.value) for r in d.rules] == [
        ("undecided", "max_pages"), ("undecided", "directive"),
    ]
    assert len({r.rule_id for r in d.rules}) == len(d.rules)


def test_a_europass_line_missing_from_one_sample_abstains_even_if_the_others_agree():
    samples = [_sample([(0, "required")]), _sample([(0, "required")]), _sample()]
    d = decide((_EU,), samples, source_url=_SRC)
    assert d.abstained and d.confidence == "UNDECIDED"


def test_two_europass_lines_pointing_opposite_ways_abstain():
    other = Candidate(text="A Europass CV is not accepted.", heading="", europass=True)
    d = decide(
        (_EU, other), _unanimous(formats=[(0, "required"), (1, "not_required")]), source_url=_SRC
    )
    assert d.abstained and d.format_value == "any"


def test_a_line_judged_none_is_neutral_beside_a_mandate():
    question = Candidate(text="Do I have to use the Europass CV?", heading="FAQ", europass=True)
    d = decide((question, _EU), _unanimous(formats=[(0, "none"), (1, "required")]), source_url=_SRC)
    assert not d.abstained and d.format_value == "europass_required"


def test_other_template_is_surfaced_not_resolved_to_nothing():
    si = Candidate(
        text="You must use SI's provided template for CV 2026/2027.", heading="", europass=False
    )
    # No europass word, so it is a CV-term candidate; the format verdict is still accepted for it
    # because the model may see a template mandate on any CV line.
    d = decide(
        (si,), _unanimous(formats=[(0, "other_template")], directives=[(0, "none", None, None)]),
        source_url=_SRC,
    )
    assert (d.format_value, d.confidence) == ("any", "UNDECIDED")
    assert [(r.key, r.value) for r in d.rules] == [("undecided", "cv_format")]


def test_a_format_verdict_for_a_non_cv_non_europass_index_is_ignored():
    # A verdict on index 1 which does not exist in candidates is discarded, not an error.
    d = decide((_EU,), _unanimous(formats=[(0, "required"), (1, "required")]), source_url=_SRC)
    assert not d.abstained and d.format_value == "europass_required"


def test_no_europass_on_the_page_is_any_extracted_and_nothing_surfaced():
    d = decide((_PAGES,), _unanimous(rules=[(0, "max_pages", 2)]), source_url=_SRC)
    assert (d.format_value, d.confidence) == ("any", "EXTRACTED")
    assert [(r.key, r.value, r.rule_id) for r in d.rules] == [("max_pages", 2, "PAGE-0-max_pages")]


def test_a_constraint_two_of_three_readings_agree_on_is_shown_not_written():
    """Owner decision 2026-09-14: advisory rules need every reading again.
    Measured the same day, the wrong-by-majority rows (d2, d5) were two
    OpenAI readings of one model outvoting the rest; one stray vote now
    surfaces the sentence instead of risking a rule nobody wrote."""
    samples = [_sample(rules=[(0, "max_pages", 2)]), _sample(rules=[(0, "max_pages", 2)]),
               _sample(rules=[(0, "max_pages", 3)])]
    d = decide((_PAGES,), samples, source_url=_SRC)
    assert [(r.key, r.value, r.rule_text) for r in d.rules] == [
        ("undecided", "max_pages", _PAGES.text)
    ]


def test_a_three_way_split_on_a_constraint_still_abstains():
    samples = [_sample(rules=[(0, "max_pages", v)]) for v in (2, 3, 4)]
    d = decide((_PAGES,), samples, source_url=_SRC)
    assert [(r.key, r.value) for r in d.rules] == [("undecided", "max_pages")]


def test_a_constraint_one_reading_did_not_give_is_not_written():
    samples = [_sample(rules=[(0, "max_pages", 2)]), _sample(rules=[(0, "max_pages", 2)]),
               _sample(directives=[(0, "none", None, None)])]
    d = decide((_PAGES,), samples, source_url=_SRC)
    assert [(r.key, r.value) for r in d.rules] == [("undecided", "max_pages")]


#: One reader block, not one sentence. Measured 2026-09-18 on MEMBIOMED's real
#: how-to-apply page: `candidates()` returned two, and the longer was 1,935
#: characters -- a whole document checklist in one <p>. Both places a quote is
#: stored cap at 1,000 (`ConstraintRule.rule_text`, `PageDirective.rule_text`),
#: so the page raised ValidationError out of derive_page_rules and took the
#: statement write down with it: three labelled rules lost to a crash.
_LONG = Candidate(
    text=(
        "Bachelor transcript: certified translation in English, and please make "
        "sure the final grade is clearly indicated on it. " * 20
    ).strip(),
    heading="Documents",
    europass=False,
)


def test_a_quote_too_long_to_store_is_clipped_and_marked_not_dropped():
    assert len(_LONG.text) > 1_000
    d = decide(
        (_LONG,),
        _unanimous(rules=[(0, "max_pages", 2)],
                   directives=[(0, "none", None, None, "applicant")]),
        source_url=_SRC,
    )
    assert [(r.key, r.value) for r in d.rules] == [("max_pages", 2)]
    assert d.rules[0].rule_text.endswith("[...]")
    assert d.rules[0].rule_text[:60] == _LONG.text[:60]


def test_a_long_quote_on_a_directive_can_still_be_read_back():
    """The worse half: a stored directive is re-validated on every read, so an
    over-long quote written here would raise inside generation and gaps, not
    only in derivation."""
    from types import SimpleNamespace

    from apps.documents.constraints import directives_from_program

    d = decide(
        (_LONG,),
        _unanimous(directives=[(0, "emphasise", "experience", None, "applicant")]),
        source_url=_SRC,
    )
    stored = directives_from_program(SimpleNamespace(cv_directives=list(d.directives)))
    assert [(x.action, x.target) for x in stored] == [("emphasise", "experience")]
    assert stored[0].rule_text.endswith("[...]")


def test_a_quote_that_fits_is_stored_verbatim():
    d = decide((_PAGES,), _unanimous(rules=[(0, "max_pages", 2)]), source_url=_SRC)
    assert d.rules[0].rule_text == _PAGES.text


_SUPERVISOR = Candidate(
    text="Short CV (max. 2 pages) from this academic supervisor.", heading="Documents",
    europass=False, third_party=True,
)


def test_a_rule_read_off_somebody_elses_cv_is_shown_not_applied():
    """Measured live 2026-09-14: under the majority rule two of three readings
    attributed this page limit to the applicant. The prompt's own rule did not
    hold it, so the outcome is guarded in code and the student sees the
    quote instead of a rule about a different person's document."""
    d = decide((_SUPERVISOR,), _unanimous(rules=[(0, "max_pages", 2)]), source_url=_SRC)
    assert not d.abstained
    assert [(r.key, r.value, r.rule_text) for r in d.rules] == [
        ("undecided", "third_party", _SUPERVISOR.text)
    ]


def test_a_line_about_somebody_else_the_readings_judged_none_surfaces_nothing():
    d = decide((_SUPERVISOR,), _unanimous(directives=[(0, "none", None, None)]), source_url=_SRC)
    assert not d.abstained and d.rules == () and d.directives == ()


def test_a_directive_read_off_somebody_elses_cv_is_shown_not_applied():
    d = decide((_SUPERVISOR,),
               _unanimous(directives=[(0, "emphasise", "experience", None)]), source_url=_SRC)
    assert d.directives == ()
    assert [(r.key, r.value) for r in d.rules] == [("undecided", "third_party")]


#: The same requirement in German, about the host's CV. _THIRD_PARTY is ten
#: English words, so `third_party` is False here and only the readings' own
#: attribution can hold the line.
_GASTGEBER = Candidate(
    text="Lebenslauf des Gastgebers (max. 2 Seiten).", heading="Unterlagen",
    europass=False, third_party=False,
)


def test_a_line_the_readings_attribute_to_somebody_else_is_shown_not_applied():
    """The guard the regex cannot reach: a page in any language says whose CV
    it means, and the readings answer it in the schema."""
    d = decide(
        (_GASTGEBER,),
        _unanimous(rules=[(0, "max_pages", 2)],
                   directives=[(0, "none", None, None, "third_party")]),
        source_url=_SRC,
    )
    assert not d.abstained
    assert [(r.key, r.value, r.rule_text) for r in d.rules] == [
        ("undecided", "third_party", _GASTGEBER.text)
    ]


def test_one_reading_calling_the_attribution_unclear_withholds_the_line():
    """`unclear` abstains: a reading that cannot tell whose CV a sentence means
    is not a reading that said the applicant's."""
    samples = [
        _sample(rules=[(0, "max_pages", 2)], directives=[(0, "none", None, None, w)])
        for w in ("applicant", "applicant", "unclear")
    ]
    d = decide((_GASTGEBER,), samples, source_url=_SRC)
    assert [(r.key, r.value) for r in d.rules] == [("undecided", "third_party")]


def test_a_line_every_reading_attributes_to_the_applicant_is_applied():
    d = decide(
        (_GASTGEBER,),
        _unanimous(rules=[(0, "max_pages", 2)],
                   directives=[(0, "none", None, None, "applicant")]),
        source_url=_SRC,
    )
    assert [(r.key, r.value) for r in d.rules] == [("max_pages", 2)]


def test_the_regex_still_holds_a_line_every_reading_calls_the_applicants():
    """Second opinion, not replaced: the readings agreed this supervisor's
    page limit was the applicant's, which is the 2026-09-14 measurement."""
    d = decide(
        (_SUPERVISOR,),
        _unanimous(rules=[(0, "max_pages", 2)],
                   directives=[(0, "none", None, None, "applicant")]),
        source_url=_SRC,
    )
    assert [(r.key, r.value) for r in d.rules] == [("undecided", "third_party")]


def test_a_directive_verdict_without_an_attribution_is_rejected_by_the_schema():
    with pytest.raises(ValidationError):
        Directive.model_validate({"statement_index": 0, "action": "none"})


def test_a_cv_line_no_sample_judged_abstains_the_page():
    d = decide((_PAGES,), _unanimous(), source_url=_SRC)
    assert d.abstained and d.confidence == "UNDECIDED"


def test_one_sample_voting_three_times_is_not_three_samples_agreeing():
    """Votes are counted per sample. Before this fix, one reading that emitted
    `required` three times while the other two said only `directive none`
    passed as unanimous and wrote europass_required from a single reading."""
    loud = Derivations(formats=tuple(
        FormatVerdict(statement_index=0, value="required") for _ in range(_SAMPLES)
    ))
    silent = _sample(directives=[(0, "none", None, None)])
    d = decide((_EU,), [loud, silent, silent], source_url=_SRC)
    assert d.abstained and d.format_value == "any"


def _twice():
    """One reading that failed to settle on one directive for one line."""
    return Derivations(directives=(
        Directive(statement_index=0, action="include", target="education.ects_credits",
                  about_whom="applicant"),
        Directive(statement_index=0, action="include", target="education.ects_credits",
                  about_whom="applicant"),
    ))


def test_one_sample_emitting_two_directives_for_one_line_is_dissent():
    """It is ONE dissenting vote, never the answer -- and under unanimity one
    dissenting vote is enough to keep the directive from being written."""
    once = _sample(directives=[(0, "include", "education.ects_credits", None)])
    d = decide((_ECTS,), [_twice(), once, once], source_url=_SRC)
    assert d.directives == ()
    assert [(r.key, r.value) for r in d.rules] == [("undecided", "directive")]


def test_one_dissenting_reading_and_two_that_differ_write_nothing():
    samples = [_twice(),
               _sample(directives=[(0, "include", "education.ects_credits", None)]),
               _sample(directives=[(0, "unapplied", None, None)])]
    d = decide((_ECTS,), samples, source_url=_SRC)
    assert d.directives == ()
    assert [(r.key, r.value) for r in d.rules] == [("undecided", "directive")]


def test_a_unanimous_include_directive_is_written_with_the_sentence():
    d = decide((_ECTS,), _unanimous(directives=[(0, "include", "education.ects_credits", None)]),
               source_url=_SRC)
    assert d.directives == ({
        "action": "include", "target": "education.ects_credits", "value": None,
        "rule_text": _ECTS.text, "source_url": _SRC,
    },)


def test_a_unanimous_order_and_emphasise_are_written():
    rev = Candidate(
        text="A curriculum vitae in reverse chronological order.", heading="", europass=False
    )
    hi = Candidate(text="The CV should highlight your academic and professional experiences.",
                   heading="", europass=False)
    samples = _unanimous(directives=[(0, "order", "education", "reverse_chronological"),
                                     (1, "emphasise", "experience", None)])
    d = decide((rev, hi), samples, source_url=_SRC)
    assert [(x["action"], x["target"], x["value"]) for x in d.directives] == [
        ("order", "education", "reverse_chronological"), ("emphasise", "experience", None),
    ]


def test_unanimous_unapplied_is_surfaced_with_the_quote():
    q = Candidate(text="Include details on the recognition of the awarding institution.",
                  heading="CV", europass=False)
    d = decide((q,), _unanimous(directives=[(0, "unapplied", None, None)]), source_url=_SRC)
    assert [(r.key, r.value, r.rule_text, r.rule_id) for r in d.rules] == [
        ("unapplied", "cv", q.text, "PAGE-0-unapplied"),
    ]
    assert d.directives == ()


def test_a_directive_two_of_three_readings_agree_on_is_shown_not_written():
    """The d2 shape: one reading maps a sentence onto an include target the
    other two call unapplied. Nothing is written; the student sees it."""
    samples = [_sample(directives=[(0, "include", "education.ects_credits", None)]),
               _sample(directives=[(0, "unapplied", None, None)]),
               _sample(directives=[(0, "include", "education.ects_credits", None)])]
    d = decide((_ECTS,), samples, source_url=_SRC)
    assert d.directives == ()
    assert [(r.key, r.value) for r in d.rules] == [("undecided", "directive")]


def test_too_few_surviving_samples_abstains_everything():
    d = decide((_EU, _PAGES), [_sample([(0, "required")], [(1, "max_pages", 2)])], source_url=_SRC)
    assert d.abstained and d.directives == ()
    # Every candidate is surfaced: outcomes() never ran, so nothing is settled.
    assert [(r.key, r.value) for r in d.rules] == [
        ("undecided", "cv_format"), ("undecided", "unjudged"),
    ]


def test_outcomes_are_per_candidate_and_carry_what_disagreed():
    samples = [_sample([(0, "required")], [(1, "max_pages", v)]) for v in (2, 3, 4)]
    got = outcomes((_EU, _PAGES), samples)
    assert got[0].format_action == "EUROPASS" and got[0].kind == "format"
    assert got[1].kind == "undecided" and got[1].disputed == ("max_pages",)


# --- live: the gate -------------------------------------------------------------
#
# Every sentence here was measured 2026-09-13: the keyword rule scored 61%
# and was wrong in the PII direction on unseen phrasing; a local NLI model
# 54%; OPENAI_EXTRACTION_MODEL 98% by label and 100% unanimous on the
# action. This pins that number to the configured model. A model change is a
# red test until it is re-run. 2026-09-14: the third reading moved to
# ANTHROPIC_JUDGE_MODEL; every number below predates that. Re-measured the same
# day over 17 rounds (CLAUDE.md): zero wrong Europass actions, but this gate
# passes only ~4 in 5 rounds, failing on an intermittent majority-wrong
# advisory row (d2/d5) that the OpenAI-only judge shows too.
# An abstention (an undecided or unjudged
# outcome) is the design's safe outcome, not a wrong action -- the gate
# forbids wrong actions outright everywhere, and caps abstentions separately
# for the two dimensions this corpus judges. Measured 2026-09-13, three live
# runs under the old unanimity rule: the 34 europass/standard rows -- the PII
# decision this design exists for -- were 0 undecided and 0 wrong every time.
# The 14 advisory rows (constraint/include/order/emphasise/unapplied/none)
# abstained on 4-5 of 14 per run (29-36%), churning among goettingen-de / d2 /
# d3 / d4 / d5.
#
# On 2026-09-14 an advisory rule briefly acted on a MAJORITY of the surviving
# readings (cap ceil(15%)), and went back to unanimity the same day, owner
# decision, after the only wrong answers in 17 rounds were majority-written
# advisory rows. Under unanimity with Claude as the third reading, 6 full
# rounds abstained on 1, 2, 3, 1, 5 and 1 advisory rows, so the cap is back to
# ceil(30%), its value under unanimity before. With the one retry for a
# missing or thin reading (same day), 5 live rounds passed: 0 wrong, 0-1 format
# and 1-3 advisory rows undecided, three readings every time.
# Measured on the first run under the new rule: 48/48 correct, 0 wrong, 0/34
# format and 0/14 advisory undecided. The same run before the third-party
# guard was 47/48 -- swiss-3rd, the supervisor's page limit written as the
# applicant's -- which is what relaxing to a majority costs when nothing
# holds the attribution. The file grows from abstained cases a human
# resolves; a wrong answer a majority agrees on never abstains and never
# lands here -- that blind spot is recorded in the spec, not hidden by this
# test.

_EVAL = pathlib.Path(__file__).resolve().parents[2] / "docs/research/cv-format-eval.csv"


def _matches(expect: str, detail: str, got: Outcome) -> bool:
    """Correctness for the four directive-shaped outcomes plus `unapplied`,
    per the design's `ok` expression. `europass`/`standard`/`none` are judged
    separately by `_classify` -- they need to distinguish a wrong verdict
    from an abstention, which these four never abstain on individually."""
    if expect == "constraint":
        key, _, value = detail.partition("=")
        constraints = dict(got.constraints)
        return constraints.get(key) is not None and str(constraints[key]) == value
    if expect == "include":
        return got.directive == ("include", detail, None)
    if expect == "order":
        return got.directive == ("order", *detail.split("="))
    if expect == "emphasise":
        return got.directive == ("emphasise", detail, None)
    if expect == "unapplied":
        return got.directive == ("unapplied", None, None)
    return False


def _classify(expect: str, detail: str, got: Outcome) -> str:
    """"correct" / "undecided" / "wrong" for one eval row.

    Ruling 1 (2026-09-13 controller adjudication): a europass/standard row is
    judged on `format_action` alone -- a dispute on some other field of the
    same candidate (a photo rule, an order directive) must not fail a row
    whose format verdict was unanimous and right. `none` accepts either the
    kind=="none" shape or a NEUTRAL verdict with nothing else attached. Every
    other outcome keeps the brief's original per-kind check via `_matches`.
    """
    if expect in ("europass", "standard"):
        wanted = "EUROPASS" if expect == "europass" else "STANDARD"
        if got.format_action == wanted:
            return "correct"
        if got.format_action is None:
            return "undecided"
        return "wrong"
    if expect == "none":
        # A constraint, or a directive that isn't the explicit "none" verdict,
        # is a wrong attribution to the applicant's own CV -- checked before
        # the abstention check so it can never hide behind a dispute on some
        # other field of the same candidate (swiss-3rd: the model agreed
        # unanimously on max_pages=2, attributing a supervisor's page limit
        # to the applicant; that is wrong, not undecided).
        has_directive = got.directive is not None and got.directive[0] != "none"
        if got.constraints or has_directive:
            return "wrong"
        # Shown to the student, applied to nothing: that IS the design's
        # outcome for a sentence about somebody else's CV, not an abstention.
        if got.kind == "undecided" and "third_party" in got.disputed:
            return "correct"
        if got.kind == "none" or got.format_action in (None, "NEUTRAL"):
            return "correct"
        if got.kind in ("undecided", "unjudged"):
            return "undecided"
        return "wrong"
    if _matches(expect, detail, got):
        return "correct"
    if got.kind in ("undecided", "unjudged"):
        return "undecided"
    return "wrong"


@pytest.mark.live
def test_the_eval_corpus_has_no_wrong_action_and_few_abstentions(capsys):
    openai = pytest.importorskip("openai")
    anthropic = pytest.importorskip("anthropic")
    from django.conf import settings

    from apps.documents.derive import outcomes

    rows = list(csv.DictReader(_EVAL.open(encoding="utf-8")))
    page_text = "\n".join(r["sentence"] for r in rows)
    found = candidates(page_text, ())
    assert len(found) == len(rows), "every eval sentence must be a candidate by code"
    listing = "\n".join(f"{i} | {c.text}" for i, c in enumerate(found))
    samples = _judge(
        openai.OpenAI().responses, anthropic.Anthropic().messages,
        program_id="eval", listing=listing,
    )
    assert len(samples) == _SAMPLES
    per = outcomes(found, samples)

    format_outcomes = ("europass", "standard")
    n_format = sum(1 for r in rows if r["outcome"] in format_outcomes)
    n_advisory = len(rows) - n_format

    undecided = []
    wrong = []
    format_undecided = 0
    advisory_undecided = 0
    for i, row in enumerate(rows):
        got = per[i]
        expect = row["outcome"]
        verdict = _classify(expect, row["detail"], got)
        if verdict == "undecided":
            undecided.append((row["id"], expect, row["detail"], got))
            if expect in format_outcomes:
                format_undecided += 1
            else:
                advisory_undecided += 1
        elif verdict == "wrong":
            wrong.append((row["id"], expect, row["detail"], got))
    correct = len(rows) - len(undecided) - len(wrong)
    with capsys.disabled():
        print(
            f"\n{settings.OPENAI_EXTRACTION_MODEL} x2 + {settings.ANTHROPIC_JUDGE_MODEL}: "
            f"{correct}/{len(rows)} correct, "
            f"{len(wrong)} wrong; format rows {format_undecided}/{n_format} undecided, "
            f"advisory rows {advisory_undecided}/{n_advisory} undecided"
        )
        for u in undecided:
            print("  ~", u)
        for w in wrong:
            print("  X", w)
    assert wrong == []
    assert format_undecided <= 1
    assert advisory_undecided <= math.ceil(0.3 * n_advisory)
