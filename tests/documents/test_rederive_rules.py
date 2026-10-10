from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.documents.grammar import Rule
from apps.funding.models import OfficialSource, OfficialSourceSnapshot, ProgramStatement
from apps.research.decisions import DecisionsUnavailable

pytestmark = pytest.mark.django_db


def _statement(program, text, *, kind="DOCUMENT"):
    source = OfficialSource.objects.create(
        canonical_url=f"https://official.example/{uuid4()}",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, s3_key=f"official-sources/{uuid4()}", s3_version_id="1",
        sha256="0" * 64, final_url=source.canonical_url, redirect_chain=[],
        retrieved_at=timezone.now(), admissions_cycle="2027", content_type="text/html",
        byte_size=1,
    )
    return ProgramStatement.objects.create(
        program=program, snapshot=snapshot, kind=kind, requirement="REQUIRED",
        text=text, label=text[:40],
    )


@pytest.fixture
def grammar(monkeypatch):
    """Stub both grammar requests at their module seams: every stored sentence
    reads as `rule` (a dict of Rule fields), or as nothing."""

    def install(rule=None, *, raises=None):
        def read_slots(found, **kwargs):
            if raises is not None:
                raise raises
            return ()

        def read_values(found, slots, **kwargs):
            if rule is None:
                return ()
            return tuple(Rule(index=i, sentence=c.text, confidence=0.95, **rule)
                         for i, c in enumerate(found))

        monkeypatch.setattr("apps.documents.grammar_questions.read_slots", read_slots)
        monkeypatch.setattr("apps.documents.grammar_values.read_values", read_values)

    return install


_PAGES_2 = {"document": "cv", "operation": "limit", "value": 2, "unit": "pages",
            "bound": "maximum"}


def test_a_stored_sentence_yields_its_rule_without_a_page(program_factory, grammar):
    """§6.5: when the grammar grows, every programme that ever stated the rule
    gets it -- without refetching a single page."""
    grammar(_PAGES_2)
    program = program_factory()
    _statement(program, "Your CV may not exceed two pages.")
    call_command("rederive_rules", stdout=StringIO())
    program.refresh_from_db()
    assert [(r["key"], r["value"]) for r in program.cv_constraints] == [("max_pages", 2)]


def test_nothing_is_fetched(program_factory, grammar, monkeypatch):
    grammar()
    _statement(program_factory(), "Your CV may not exceed two pages.")

    def explode(*args, **kwargs):  # pragma: no cover
        raise AssertionError("the sweep refetched a page")

    monkeypatch.setattr("apps.research.discovery.retrieve_official_source", explode)
    call_command("rederive_rules", stdout=StringIO())


def test_a_dry_run_writes_nothing_and_reports_what_would_change(program_factory, grammar):
    grammar(_PAGES_2)
    program = program_factory()
    _statement(program, "Your CV may not exceed two pages.")
    out = StringIO()
    call_command("rederive_rules", "--dry-run", stdout=out)
    program.refresh_from_db()
    assert program.cv_constraints == []
    assert "max_pages" in out.getvalue()


def test_the_sweep_stops_on_its_budget_rather_than_running_unbounded(program_factory,
                                                                     settings):
    """CLAUDE.md names this exact sweep as the one that makes an unbounded model
    call per programme unless it adds its own limiter. The real ask() is used:
    the budget refuses before any request, so the key is never sent."""
    settings.DECISIONS_RUN_TOKENS = 1
    # With a key: no key is `not_configured`, which ask() checks first.
    settings.OPENROUTER_API_KEY = "or-test-key"
    for _ in range(3):
        _statement(program_factory(), "Your CV may not exceed two pages.")
    out = StringIO()
    call_command("rederive_rules", stdout=out)
    assert "budget" in out.getvalue().lower()


def test_with_no_provider_the_sweep_stops_and_writes_nothing(program_factory, grammar):
    """No frontier fallback here: the sweep exists to ask the grammar again."""
    # <!-- reconciled 2026-09-26: the kind Tasks 1-3 raise for a missing key -->
    grammar(raises=DecisionsUnavailable("OPENROUTER_API_KEY is not set", kind="not_configured"))
    program = program_factory()
    _statement(program, "Your CV may not exceed two pages.")
    out = StringIO()
    call_command("rederive_rules", stdout=out)
    program.refresh_from_db()
    assert program.cv_constraints == []
    assert "unavailable" in out.getvalue()


def test_one_programmes_stop_does_not_roll_back_an_earlier_committed_programme(
    program_factory, monkeypatch
):
    """Controller ruling: each programme's read-ask-write is its own
    `_atomic_keeping_decisions` block, so a decision-layer stop on the SECOND
    programme in the run must not undo the write the FIRST one already
    committed. `canonical_key` orders the sweep, so "first" and "second" are
    the test's to control."""
    first = program_factory(canonical_key="aaa-first")
    second = program_factory(canonical_key="bbb-second")
    _statement(first, "Your CV may not exceed two pages.")
    _statement(second, "Your CV may not exceed three pages.")

    calls = {"n": 0}

    def read_slots(found, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise DecisionsUnavailable("outage", kind="failed")
        return ()

    def read_values(found, slots, **kwargs):
        return tuple(Rule(index=i, sentence=c.text, confidence=0.95, **_PAGES_2)
                     for i, c in enumerate(found))

    monkeypatch.setattr("apps.documents.grammar_questions.read_slots", read_slots)
    monkeypatch.setattr("apps.documents.grammar_values.read_values", read_values)

    out = StringIO()
    call_command("rederive_rules", stdout=out)

    first.refresh_from_db()
    second.refresh_from_db()
    assert [(r["key"], r["value"]) for r in first.cv_constraints] == [("max_pages", 2)]
    assert second.cv_constraints == []
    assert "unavailable" in out.getvalue()


def test_a_programme_with_no_statements_is_skipped(program_factory, grammar):
    grammar(_PAGES_2)
    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 2,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": "",
    }])
    call_command("rederive_rules", stdout=StringIO())
    program.refresh_from_db()
    # Untouched: an empty re-derivation here would erase rules a read DID produce.
    assert program.cv_constraints[0]["rule_text"] == "old"


def test_a_dry_run_asks_the_provider_but_writes_no_decision_record(
    program_factory, monkeypatch, settings
):
    """Fix round 1, finding 1: `_grammar_rules` used to be asked with its
    `record=True` default even under --dry-run, so a dry run spent a
    DecisionRecord row (and tokens against the cache) despite promising to
    write nothing. The real `ask()` is exercised here, through a fake
    provider transport, so the assertion is about the real cache write, not
    a stub that never reaches it."""
    from apps.research.decisions import Answer, Choice
    from apps.research.models import DecisionRecord

    settings.DECISIONS_PROVIDER = {"default": "typesafe"}
    # ask() checks the route is configured before it reaches the transport.
    settings.OPENROUTER_API_KEY = "or-test-key"

    def transport(state, questions, *, model, provider):
        answers = {}
        for qid, q in questions.items():
            value = q.options[0] if isinstance(q, Choice) else False
            answers[qid] = Answer(id=qid, value=value, confidence=0.99,
                                  probabilities={str(value): 0.99}, model=model,
                                  provider=provider, input_tokens=0)
        return answers

    monkeypatch.setattr("apps.research.decisions._typesafe_client", transport)
    program = program_factory()
    _statement(program, "Your CV may not exceed two pages.")

    call_command("rederive_rules", "--dry-run", stdout=StringIO())

    assert DecisionRecord.objects.count() == 0
    program.refresh_from_db()
    assert program.cv_constraints == []


def test_a_competency_statement_is_never_asked_about(program_factory, monkeypatch):
    """Fix round 1, finding 2: the sweep must gather the same statement kinds
    derive_page_rules asks the grammar about (FORMAT, DOCUMENT) -- never a
    COMPETENCY/LANGUAGE/OTHER statement."""
    program = program_factory()
    _statement(program, "Fluent in Python and data analysis.", kind="COMPETENCY")

    def explode(*args, **kwargs):  # pragma: no cover
        raise AssertionError("a COMPETENCY statement reached the grammar")

    monkeypatch.setattr("apps.documents.grammar_questions.read_slots", explode)
    call_command("rederive_rules", stdout=StringIO())
    program.refresh_from_db()
    assert program.cv_constraints == []


_THIRD_PARTY_LIMIT = {"document": "cv", "operation": "limit", "value": 2, "unit": "pages",
                      "bound": "maximum", "note": "third_party"}


def test_a_third_party_statement_keeps_a_note_not_an_empty_list(program_factory, grammar):
    """Fix round 1, finding 3: a programme whose stored statements are all
    about somebody else's document (a supervisor's own CV, say) must not be
    erased to an empty rule set -- it keeps an undecided/third_party note the
    student still sees."""
    grammar(_THIRD_PARTY_LIMIT)
    program = program_factory()
    _statement(program, "Short CV (max. 2 pages) from your academic supervisor.")

    call_command("rederive_rules", stdout=StringIO())

    program.refresh_from_db()
    assert program.cv_constraints != []
    assert program.cv_constraints[0]["key"] == "undecided"


# Final review I3: the sweep sees only stored FORMAT/DOCUMENT statements, but a
# page read also sees code-found lines. So it never writes the format switch,
# and it replaces only the rules whose sentence it re-read.
def _stored(rule_id, key, value, rule_text):
    return {"rule_id": rule_id, "key": key, "value": value,
            "enforcement": "ADVISORY_HIGH_RISK", "rule_text": rule_text,
            "source_url": "", "scope": "PROGRAMME"}


def test_a_page_read_europass_requirement_survives_a_sweep(program_factory, grammar):
    from apps.funding.models import Program

    grammar(_PAGES_2)
    program = program_factory(
        cv_format_requirement=Program.CVFormatRequirement.EUROPASS_REQUIRED,
        cv_format_confidence=Program.CVFormatConfidence.EXTRACTED,
    )
    _statement(program, "Your CV may not exceed two pages.")
    call_command("rederive_rules", stdout=StringIO())
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.EUROPASS_REQUIRED
    assert program.cv_format_confidence == Program.CVFormatConfidence.EXTRACTED
    assert ("max_pages", 2) in [(r["key"], r["value"]) for r in program.cv_constraints]


def test_a_code_found_rule_not_among_the_statements_survives_a_sweep(
    program_factory, grammar
):
    """Kept whole, and a re-read note on the same index never takes its id:
    resolve_rules slots notes by rule_id, so a shared id would silently drop
    one of them."""
    from apps.documents.constraints import rules_from_program

    grammar({"document": "cv", "operation": "format", "value": None, "note": "unsure"})
    code_found = _stored("PAGE-0-unsure", "undecided", "cv:format",
                         "Europass CV is not accepted.")
    directive = {"action": "emphasise", "target": "research", "value": None,
                 "rule_text": "Emphasise your research.", "source_url": ""}
    program = program_factory(cv_constraints=[code_found], cv_directives=[directive])
    _statement(program, "Please send a CV in a suitable format.")

    call_command("rederive_rules", stdout=StringIO())

    program.refresh_from_db()
    assert code_found in program.cv_constraints
    assert program.cv_directives == [directive]
    ids = [r.rule_id for r in rules_from_program(program)]
    assert len(ids) == len(set(ids)) == 2


def test_a_re_read_sentence_replaces_its_own_old_rule(program_factory, grammar):
    grammar(_PAGES_2)
    sentence = "Your CV may not exceed two pages."
    program = program_factory(cv_constraints=[_stored("PAGE-4-max_pages", "max_pages", 3,
                                                      sentence)])
    _statement(program, sentence)
    call_command("rederive_rules", stdout=StringIO())
    program.refresh_from_db()
    assert [(r["key"], r["value"]) for r in program.cv_constraints] == [("max_pages", 2)]


def test_a_stored_reference_sentence_yields_its_referee_record(program_factory, grammar):
    """The referee operation is new; the sweep is how every programme already
    read gets it without a refetch (CLAUDE.md: add the operation, then run
    rederive_rules)."""
    grammar({"document": "reference_letter", "operation": "referee",
             "value": ("count", "TWO")})
    program = program_factory()
    _statement(program, "Two letters of recommendation are required.")

    call_command("rederive_rules", stdout=StringIO())

    program.refresh_from_db()
    assert [(r["field"], r["value"]) for r in program.referee_requirements] == [("count", "TWO")]
    assert program.referee_requirements[0]["rule_text"] == (
        "Two letters of recommendation are required.")
