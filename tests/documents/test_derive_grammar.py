"""derive_page_rules end to end, over a stubbed grammar.

The stubs sit at the grammar's module seams (read_slots, read_values,
read_page_facts), not at question ids: what is under test is what lands on the
Program and the ApplicationPrompt, and the question ids are Tasks 5-6's to
change. Every test asserts an OUTCOME.
"""
from dataclasses import replace
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from apps.documents import derive
from apps.documents.derive import Decision, derive_page_rules
from apps.documents.grammar import Rule, Slotted
from apps.documents.grammar_questions import PageFacts
from apps.documents.letter_shape import LetterShape
from apps.funding.models import (
    ApplicationPrompt,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
    ProgramStatement,
)
from apps.research.decisions import DecisionsUnavailable

pytestmark = pytest.mark.django_db


# <!-- reconciled 2026-09-26: the kind Tasks 1-3 raise for a missing key -->
def _no_key() -> DecisionsUnavailable:
    return DecisionsUnavailable("OPENROUTER_API_KEY is not set", kind="not_configured")

_CV = "Your CV may not exceed two pages."
_LETTER = "The motivation letter must be at most 800 words."
_PAGE = f"# Application documents\n{_CV}\n{_LETTER}\nA photograph is not required.\n"


def _snapshot() -> OfficialSourceSnapshot:
    # tests/documents/test_derive.py:59-77 -- the factory master actually uses.
    source = OfficialSource.objects.create(
        canonical_url=f"https://official.example/{uuid4()}",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    return OfficialSourceSnapshot.objects.create(
        source=source, s3_key=f"official-sources/{uuid4()}", s3_version_id="1",
        sha256="0" * 64, final_url=source.canonical_url, redirect_chain=[],
        retrieved_at=timezone.now(), admissions_cycle="2027", content_type="text/html",
        byte_size=1,
    )


@pytest.fixture
def grammar(monkeypatch):
    """Install the grammar's answers: `script` maps a sentence to the rules the
    two requests would have produced for it, `page` is the page-level reading.
    Returns what the stubs saw."""

    def install(script=None, *, page=PageFacts(), raises=None):
        script = script or {}
        seen: dict[str, object] = {}

        def read_slots(found, **kwargs):
            seen["client"] = kwargs.get("client")
            if raises is not None:
                raise raises
            return tuple(
                Slotted(index=i, document="other", document_confidence=0.99,
                        operation="other", operation_confidence=0.99,
                        third_party=False, conditional=False)
                for i in range(len(found))
            )

        def read_values(found, slots, **kwargs):
            return tuple(
                Rule(index=i, sentence=c.text, heading=c.heading, **{"confidence": 0.95, **kw})
                for i, c in enumerate(found)
                for kw in script.get(c.text, ())
            )

        def read_page_facts(found, slots, **kwargs):
            return page

        monkeypatch.setattr("apps.documents.grammar_questions.read_slots", read_slots)
        monkeypatch.setattr("apps.documents.grammar_values.read_values", read_values)
        monkeypatch.setattr("apps.documents.grammar_questions.read_page_facts", read_page_facts)
        return seen

    return install


def _letter(**kw):
    return {"document": "motivation_letter", **kw}


def _prompt(program) -> ApplicationPrompt:
    return ApplicationPrompt.objects.get(programme=program, cycle="2027")


def test_a_page_limit_lands_on_the_program_as_an_advisory_rule(program_factory, grammar):
    grammar({_CV: [{"document": "cv", "operation": "limit", "value": 2, "unit": "pages",
                    "bound": "maximum"}]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    assert [(r["key"], r["value"]) for r in program.cv_constraints] == [("max_pages", 2)]
    assert program.cv_constraints[0]["enforcement"] == "ADVISORY_HIGH_RISK"


def test_the_client_reaches_the_grammar(program_factory, grammar):
    seen = grammar()
    client = object()
    derive_page_rules(program_factory(), page_text=_PAGE, snapshot=_snapshot(), client=client)
    assert seen["client"] is client


def test_a_page_stating_no_format_rule_writes_any_and_extracted(program_factory, grammar):
    grammar()
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.ANY
    assert program.cv_format_confidence == Program.CVFormatConfidence.EXTRACTED


def test_a_europass_page_switches_the_format(program_factory, grammar):
    page = "# Documents\nCV in the Europass CV template.\n"
    grammar({"CV in the Europass CV template.": [
        {"document": "cv", "operation": "format", "value": "europass_required"}
    ]})
    program = program_factory()
    derive_page_rules(program, page_text=page, snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.EUROPASS_REQUIRED


def test_a_hand_verified_format_is_never_overwritten_but_rules_still_land(program_factory,
                                                                          grammar):
    grammar({_CV: [{"document": "cv", "operation": "limit", "value": 2, "unit": "pages"}]})
    program = program_factory(
        cv_format_requirement=Program.CVFormatRequirement.FUNDER_TEMPLATE,
        cv_format_verified_for_cycle="2026/27",
    )
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.FUNDER_TEMPLATE
    assert program.cv_constraints[0]["key"] == "max_pages"


def test_a_page_with_no_candidate_replaces_the_previous_rules_and_asks_nothing(
    program_factory, grammar
):
    """Kept from master: no CV or letter line found by code is NO_CV_FOUND, and
    the previous rows go -- spec §5.3's replace-on-empty, without a request."""
    seen = grammar(raises=AssertionError("the grammar was asked about an empty page"))
    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 2,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": "",
    }])
    derive_page_rules(program, page_text="# About us\nWe are a university.\n",
                      snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    assert program.cv_constraints == []
    assert program.cv_format_confidence == Program.CVFormatConfidence.NO_CV_FOUND
    assert "client" not in seen


def test_an_unsure_sentence_becomes_a_note_the_counsellor_reads(program_factory, grammar):
    grammar({_CV: [{"document": "cv", "operation": "limit", "value": None, "note": "unsure",
                    "confidence": 0.44}]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    notes = [r for r in program.cv_constraints if r["key"] in ("undecided", "unapplied")]
    assert notes and notes[0]["rule_text"] == _CV


def test_nothing_writes_a_consultant_task(program_factory, grammar):
    """Owner decision 2026-09-23: no person in the pipeline."""
    from apps.research.models import ConsultantResearchTask

    grammar({_CV: [{"document": "cv", "operation": "other", "value": None,
                    "note": "unapplied"}]})
    derive_page_rules(program_factory(), page_text=_PAGE, snapshot=_snapshot(), client=object())
    # _base_manager: every tenant's rows, and no tenant scope to hold (the
    # TenantManager raises TenantContextMissing outside one).
    assert ConsultantResearchTask._base_manager.count() == 0


# --- Nothing typed is lost (addendum §6.3): each field the frontier path writes,
# --- written by the grammar path, end to end onto the stored rows.

def test_the_letter_cap_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="limit", value=800, unit="words", bound="maximum")]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    assert _prompt(program).letter_max_words == 800


def test_form_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="form", value="formal_letter")]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    prompt = _prompt(program)
    assert prompt.letter_form == "FORMAL_LETTER"
    assert prompt.letter_shape_sources["form"]["text"] == _LETTER


def test_naming_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="naming", value="forbidden")]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    assert _prompt(program).letter_naming == "FORBIDDEN"


def test_document_required_is_written_with_its_witness(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="limit", value=800, unit="words")]},
            page=PageFacts(letter_required="REQUIRED"))
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    prompt = _prompt(program)
    assert prompt.letter_document_required == "REQUIRED"
    assert prompt.letter_shape_sources["document_required"]["text"] == _LETTER


def test_track_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="limit", value=800, unit="words")]},
            page=PageFacts(track="research"))
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    program.refresh_from_db()
    assert program.academic_track == "research"


def test_portfolio_led_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="limit", value=800, unit="words")]},
            page=PageFacts(portfolio_led=True))
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    program.refresh_from_db()
    assert program.portfolio_led is True


def test_the_letters_language_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="language", value="de")]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    assert _prompt(program).document_language == "de"


def test_a_range_writes_its_floor_and_its_cap(program_factory, grammar):
    grammar({_LETTER: [
        _letter(operation="limit", value=300, unit="words", bound="minimum"),
        _letter(operation="limit", value=500, unit="words", bound="maximum"),
    ]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    prompt = _prompt(program)
    assert (prompt.letter_min_words, prompt.letter_max_words) == (300, 500)


def test_a_character_floor_is_written(program_factory, grammar):
    grammar({_LETTER: [
        _letter(operation="limit", value=2800, unit="characters", bound="minimum")
    ]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    assert _prompt(program).letter_min_chars == 2800


def test_a_tolerance_is_a_written_requirement(program_factory, grammar):
    # <!-- reconciled 2026-09-26: a tolerance is a topic sentence, never a limit bound -->
    grammar({_LETTER: [_letter(operation="topic", value=_LETTER)]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    assert [w["text"] for w in _prompt(program).letter_written_requirements] == [_LETTER]


# --- Which path reads the page (addendum §2, §5.1).

def test_with_no_provider_configured_the_frontier_judge_reads_the_page(
    program_factory, grammar, monkeypatch
):
    """A missing key degrades cost, not correctness. The existing frontier
    tests in test_derive.py run this branch end to end: tests/conftest.py blanks
    every provider key, so read_and_derive reaches the judge exactly as before."""
    grammar(raises=_no_key())
    seen: dict[str, object] = {}

    def judge(found, *, parser, claude, program_id, source_url):
        seen["parser"], seen["claude"] = parser, claude
        return (
            Decision(abstained=False, format_value=Program.CVFormatRequirement.ANY,
                     confidence=Program.CVFormatConfidence.EXTRACTED, rules=(), directives=()),
            LetterShape(max_words=700,
                        sources={"max_words": {"text": _LETTER, "source_url": source_url}}),
        )

    monkeypatch.setattr(derive, "_read_by_judge", judge)
    program = program_factory()
    parser, claude = object(), object()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      parser=parser, claude=claude)
    assert (seen["parser"], seen["claude"]) == (parser, claude)
    assert _prompt(program).letter_max_words == 700


def test_with_no_provider_and_no_frontier_client_the_page_is_not_read(program_factory, grammar):
    grammar(raises=_no_key())
    with pytest.raises(DecisionsUnavailable) as raised:
        derive_page_rules(program_factory(), page_text=_PAGE, snapshot=_snapshot())
    assert raised.value.kind == "not_configured"


# <!-- review focus 3 -->
def test_an_outage_leaves_the_catalog_untouched_and_never_falls_back(
    program_factory, grammar, monkeypatch
):
    """'We learned nothing' must never reach a catalog write, and an outage is
    not a missing key: the frontier judge is not a second opinion (addendum
    §5.1). The raise propagates so read_and_derive rolls the statements back."""
    grammar(raises=DecisionsUnavailable("typesafe: ConnectTimeout", kind="failed"))

    def judge(*args, **kwargs):  # pragma: no cover
        raise AssertionError("an outage fell back to the frontier judge")

    monkeypatch.setattr(derive, "_read_by_judge", judge)
    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 2,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": "",
    }])
    with pytest.raises(DecisionsUnavailable):
        derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(),
                          parser=object(), claude=object())
    program.refresh_from_db()
    assert program.cv_constraints[0]["rule_text"] == "old"


def test_a_values_failure_after_the_slots_answered_writes_no_partial_rule_set(
    program_factory, grammar, monkeypatch
):
    """Controller ruling C15 / review focus 3: the first request answered and
    the second failed. Nothing of the page's new reading lands; the previous
    rules stand."""
    grammar()

    def read_values(found, slots, **kwargs):
        raise DecisionsUnavailable("typesafe: ConnectTimeout", kind="failed")

    monkeypatch.setattr("apps.documents.grammar_values.read_values", read_values)
    old = {"rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 2,
           "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": ""}
    program = program_factory(cv_constraints=[old])
    with pytest.raises(DecisionsUnavailable) as raised, transaction.atomic():
        derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(),
                          admissions_cycle="2027", client=object())
    assert raised.value.kind == "failed"
    program.refresh_from_db()
    assert program.cv_constraints == [old]
    assert not ApplicationPrompt.objects.filter(programme=program).exists()


def test_a_letter_note_reaches_the_counsellor_too(program_factory, grammar):
    """Letter notes go through to_notes like CV ones: nothing typed is dropped."""
    grammar({_LETTER: [_letter(operation="limit", value=None, note="unsure",
                               confidence=0.44)]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    program.refresh_from_db()
    assert [r["rule_text"] for r in program.cv_constraints
            if r["key"] in ("undecided", "unapplied")] == [_LETTER]


def test_the_frontier_path_never_resets_a_language_the_grammar_wrote(
    program_factory, grammar, monkeypatch
):
    """reads_language=True on the grammar path only: the frontier judge does not
    read the letter's language, so its re-read must not wipe one."""
    grammar({_LETTER: [_letter(operation="language", value="de")]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    assert _prompt(program).document_language == "de"

    grammar(raises=_no_key())
    monkeypatch.setattr(derive, "_read_by_judge", lambda found, **kw: (
        Decision(abstained=False, format_value=Program.CVFormatRequirement.ANY,
                 confidence=Program.CVFormatConfidence.EXTRACTED, rules=(), directives=()),
        LetterShape(),
    ))
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      parser=object(), claude=object())
    assert _prompt(program).document_language == "de"


# --- Through the real decision layer: ask() runs, only the transport is faked.

def test_sixty_candidates_with_no_key_reach_the_frontier_judge(program_factory, monkeypatch):
    """Controller ruling C2: a long page with no provider key is packed, meets
    not_configured on its first request, and is read by the judge -- never a
    size error."""
    page = "# Documents\n" + "".join(
        f"Your CV section {i} must list item {i} of the application.\n" for i in range(60)
    )
    reached: list[int] = []

    def judge(found, **kwargs):
        reached.append(len(found))
        return (
            Decision(abstained=False, format_value=Program.CVFormatRequirement.ANY,
                     confidence=Program.CVFormatConfidence.EXTRACTED, rules=(), directives=()),
            LetterShape(),
        )

    monkeypatch.setattr(derive, "_read_by_judge", judge)
    derive_page_rules(program_factory(), page_text=page, snapshot=_snapshot(),
                      parser=object(), claude=object())
    assert reached == [60]


def test_one_oversized_sentence_becomes_a_note_and_the_rest_of_the_page_is_read(
    program_factory, grammar,
):
    """Fix round 1, finding 2: ask() refuses a state over MAX_STATE_TOKENS with
    the typed StateTooLarge. A single candidate too large to ask about is
    never asked at all -- it becomes an unapplied note carrying its (clipped)
    sentence -- and the rest of the page still reaches the grammar and is
    read normally: never a failed page, never a crash."""
    huge = "Your CV " + "must list everything " * 8_000
    page = f"# Documents\n{_CV}\n{huge}\n"
    seen = grammar({_CV: [{"document": "cv", "operation": "limit", "value": 2,
                           "unit": "pages", "bound": "maximum"}]})
    program = program_factory()
    derive_page_rules(program, page_text=page, snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    # the rest of the page reached the (stubbed) grammar -- only the huge
    # sentence was withheld from it
    assert "client" in seen
    keys = [(r["key"], r.get("value")) for r in program.cv_constraints]
    assert ("max_pages", 2) in keys
    unapplied = [r for r in program.cv_constraints if r["key"] == "unapplied"]
    assert len(unapplied) == 1
    assert unapplied[0]["rule_text"].startswith("Your CV must list everything")
    assert unapplied[0]["rule_text"].endswith(" [...]")


def test_one_oversized_sentence_with_no_key_still_reaches_the_frontier_judge(
    program_factory, grammar, monkeypatch,
):
    """The size ceiling belongs to the decision layer alone. With no provider
    configured, the whole original page -- oversized sentence included --
    falls back to the frontier judge exactly as any other not_configured page
    does; the oversized candidate is not silently dropped from that fallback."""
    huge = "Your CV " + "must list everything " * 8_000
    page = f"# Documents\n{_CV}\n{huge}\n"
    grammar(raises=_no_key())
    reached: list[int] = []

    def judge(found, **kwargs):
        reached.append(len(found))
        return (
            Decision(abstained=False, format_value=Program.CVFormatRequirement.ANY,
                     confidence=Program.CVFormatConfidence.EXTRACTED, rules=(), directives=()),
            LetterShape(),
        )

    monkeypatch.setattr(derive, "_read_by_judge", judge)
    derive_page_rules(program_factory(), page_text=page, snapshot=_snapshot(),
                      parser=object(), claude=object())
    assert reached == [2]


def test_ask_raises_a_typed_exception_for_an_oversized_state():
    """Fix round 1, finding 2 (b): the typed exception, not a message match.
    The client is never called -- ask() refuses before any transport runs."""
    from apps.research.decisions import Choice, StateTooLarge, ask

    def unreached(*args, **kwargs):
        raise AssertionError("ask() should refuse before calling the client")

    huge_question = {
        f"q{i}": Choice(question="pick", options=("a", "b"), inspect="`x`")
        for i in range(4_000)
    }
    with pytest.raises(StateTooLarge) as raised:
        ask({"x": "y"}, huge_question, decision="D6.slots", client=unreached)
    assert isinstance(raised.value, ValueError)
    assert "token budget" in str(raised.value)


_CV_LIMIT = "Your CV must not exceed 2 pages."
_CV_BODY = (
    b"<html><body><main><h2>Required documents</h2>"
    b"<ul><li>Your CV must not exceed 2 pages.</li></ul></main></body></html>"
)


class _Transport:
    """Stands in for the provider behind ask(): answers the slot request, then
    refuses the values request. Counts every request that reached it."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, state, questions, *, model, provider):
        from apps.research.decisions import Answer, Choice

        self.calls += 1
        if self.calls > 1:
            raise DecisionsUnavailable("typesafe: PermissionDenied 403 (refused)",
                                       kind="refused")
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                value = "cv" if qid.endswith(":document") else "limit"
                answers[qid] = Answer(id=qid, value=value, confidence=0.99,
                                      probabilities={value: 0.99}, model=model,
                                      provider=provider, input_tokens=0)
            else:
                answers[qid] = Answer(id=qid, value=False, confidence=0.99,
                                      probabilities={"true": 0.01, "false": 0.99},
                                      model=model, provider=provider, input_tokens=0)
        # The request's tokens, charged once, as _from_sdk charges them.
        first = next(iter(answers))
        answers[first] = replace(answers[first], input_tokens=1234)
        return answers


def test_a_refusal_keeps_its_rows_and_the_spent_ones_through_the_rollback(
    program_factory, monkeypatch, settings
):
    """Carry-over from Task 3's review: the page read's rollback must not take
    the DecisionRecord rows with it. The refusal rows are what make a refusal
    'recorded once, never retried'; the answered rows are tokens actually spent,
    which month_tokens_spent must still see. The page's own writes -- the
    statements, the rules -- roll back, and the previous rules stand."""
    from apps.documents.program_rules import read_and_derive
    from apps.research.decisions import month_tokens_spent
    from apps.research.models import DecisionRecord
    from apps.research.reader import _READS, Statement, Statements
    from tests.documents.test_derive import (
        FakeResponse,
        _MemoryStore,
        _ScriptedJudge,
        _serving,
        _source,
    )

    settings.DECISIONS_PROVIDER = {"default": "typesafe"}
    # ask() checks the route is configured before it reaches the transport.
    settings.OPENROUTER_API_KEY = "or-test-key"
    transport = _Transport()
    monkeypatch.setattr("apps.research.decisions._typesafe_client", transport)
    old = {"rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 3,
           "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": ""}
    program = program_factory(cv_constraints=[old])
    read = Statements(statements=(Statement(text=_CV_LIMIT, kind="DOCUMENT",
                                            requirement="REQUIRED", label="CV length"),))

    def read_once():
        return read_and_derive(
            program=program, source=_source(), store=_MemoryStore(),
            parser=_ScriptedJudge(*([FakeResponse(output_parsed=read)] * _READS)),
            claude=object(), admissions_cycle="2027", retrieve=_serving(_CV_BODY),
        )

    with pytest.raises(DecisionsUnavailable) as raised:
        read_once()
    assert raised.value.kind == "refused" and transport.calls == 2
    rows = DecisionRecord.objects.all()
    assert {r.decision for r in rows if r.refused} == {"D6.values"}
    assert {r.decision for r in rows if not r.refused} == {"D6.slots"}
    assert month_tokens_spent() == 1234
    program.refresh_from_db()
    assert program.cv_constraints == [old]
    assert not ProgramStatement.objects.filter(program=program).exists()

    # (b) the next read: the slots come from the cache, the refusal is raised
    # from the cache, and the provider is never asked again.
    with pytest.raises(DecisionsUnavailable) as again:
        read_once()
    assert again.value.kind == "refused" and transport.calls == 2
    program.refresh_from_db()
    assert program.cv_constraints == [old]


def test_a_budget_exhausted_on_the_values_request_keeps_slot_rows_and_writes_nothing(
    program_factory, monkeypatch, settings
):
    """Fix round 1, finding 3: DecisionBudgetExhausted is a decision-layer stop
    too (_atomic_keeping_decisions._DECISIONS_STOPPED already names it). The
    budget is exhausted exactly on the second (values) request, after the
    slots answered and spent their tokens: the slot rows survive the
    rollback, the previous rules stand, and nothing partial is written."""
    from apps.documents.program_rules import read_and_derive
    from apps.research.decisions import DecisionBudget, DecisionBudgetExhausted
    from apps.research.models import DecisionRecord
    from apps.research.reader import _READS, Statement, Statements
    from tests.documents.test_derive import (
        FakeResponse,
        _MemoryStore,
        _ScriptedJudge,
        _serving,
        _source,
    )

    settings.DECISIONS_PROVIDER = {"default": "typesafe"}
    # ask() checks the route is configured before it reaches the transport.
    settings.OPENROUTER_API_KEY = "or-test-key"
    transport = _Transport()
    monkeypatch.setattr("apps.research.decisions._typesafe_client", transport)
    old = {"rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 3,
           "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": ""}
    program = program_factory(cv_constraints=[old])
    read = Statements(statements=(Statement(text=_CV_LIMIT, kind="DOCUMENT",
                                            requirement="REQUIRED", label="CV length"),))

    with pytest.raises(DecisionBudgetExhausted):
        read_and_derive(
            program=program, source=_source(), store=_MemoryStore(),
            parser=_ScriptedJudge(*([FakeResponse(output_parsed=read)] * _READS)),
            claude=object(), admissions_cycle="2027", retrieve=_serving(_CV_BODY),
            # Measured for this exact one-candidate page: the slot request's
            # own estimate is ~1,276 tokens (under this ceiling, so slots go
            # through and spend the transport's 1,234 fake input_tokens), and
            # the values request's is ~679 (1,234 + 679 = 1,913, over it) --
            # so the budget is exhausted on the SECOND request, never the first.
            budget=DecisionBudget(limit_tokens=1900),
        )
    # The budget stops ask() before it calls the transport for D6.values
    # (DecisionBudgetExhausted's own docstring: "never after one is paid
    # for"), so only the slots call ever reached it.
    assert transport.calls == 1
    rows = DecisionRecord.objects.all()
    assert {r.decision for r in rows} == {"D6.slots"}
    program.refresh_from_db()
    assert program.cv_constraints == [old]
    assert not ProgramStatement.objects.filter(program=program).exists()


# Final review I2: the third-party word list is an additive guard, but a
# naming rule names faculty by definition and a reference letter IS the
# referee's document, so the list never marks either; the model's own answer
# still does.
_NAMING = ("In the study objectives essay, references to proposed universities "
           "or faculty should not be made.")  # docs/research/letter-shape-eval.csv E-049
_REFEREE_ACTION = "Ask your referee to upload the reference letter directly to the portal."


@pytest.mark.parametrize(("sentence", "document", "operation", "model_says", "expected"), [
    (_NAMING, "motivation_letter", "naming", False, False),
    (_REFEREE_ACTION, "reference_letter", "student_action", False, False),
    (_NAMING, "motivation_letter", "naming", True, True),
    (_REFEREE_ACTION, "reference_letter", "student_action", True, True),
    ("Short CV (max. 2 pages) from this academic supervisor.", "cv", "limit", False, True),
])
def test_the_word_list_never_marks_a_naming_or_reference_letter_slot(
    monkeypatch, sentence, document, operation, model_says, expected
):
    assert derive._THIRD_PARTY.search(sentence)
    found = (derive.Candidate(text=sentence, heading="", europass=False,
                              third_party=True, cv=True, letter=True),)
    slot = Slotted(index=0, document=document, document_confidence=0.99,
                   operation=operation, operation_confidence=0.99,
                   third_party=model_says, conditional=False)
    monkeypatch.setattr("apps.documents.grammar_questions.read_slots",
                        lambda found, **kw: (slot,))
    monkeypatch.setattr("apps.documents.grammar_values.read_values",
                        lambda found, slots, **kw: ())
    _, slots = derive._grammar_rules(found, language="en", budget=None, client=None)
    assert slots[0].third_party is expected


# 2026-10-08: the reference-letter facts land on the programme as records,
# from the same read, through derive_page_rules' one write.
_REFEREES = "Two letters of recommendation must be uploaded by your referees."


def test_referee_facts_land_on_the_programme(program_factory, grammar):
    grammar({_REFEREES: [
        {"document": "reference_letter", "operation": "student_action", "value": _REFEREES},
        {"document": "reference_letter", "operation": "referee", "value": ("count", "TWO")},
        {"document": "reference_letter", "operation": "referee",
         "value": ("mode", "PORTAL_INVITE")},
    ]})
    program = program_factory()
    snapshot = _snapshot()

    derive_page_rules(program, page_text=f"{_PAGE}{_REFEREES}\n", snapshot=snapshot,
                      client=object())

    program.refresh_from_db()
    assert [(r["field"], r["value"]) for r in program.referee_requirements] == [
        ("count", "TWO"), ("mode", "PORTAL_INVITE")]
    assert {r["rule_text"] for r in program.referee_requirements} == {_REFEREES}
    assert {r["source_url"] for r in program.referee_requirements} == {snapshot.final_url}


def test_a_german_reference_sentence_reaches_the_reader_but_not_the_judge():
    """German has no generic `letter` word in the vocabulary, and the patterns
    are word-bounded, so Empfehlungsschreiben never matched. It is a candidate
    now -- for the grammar only: neither the CV nor the letter judge reads it."""
    found = derive.candidates(
        "# Bewerbung\nZwei Empfehlungsschreiben von Hochschullehrern sind erforderlich.\n",
        (), language="de",
    )
    (candidate,) = found
    assert "Empfehlungsschreiben" in candidate.text
    assert (candidate.cv, candidate.letter) == (False, False)
