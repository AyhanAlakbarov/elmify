"""The ship gates of spec §11, amended by the 2026-09-26 addendum.

Gate 7 (expressibility) is a set of plain tests and runs everywhere. It pins
`docs/research/rule-grammar-map.csv`, which was DRAFTED BY AN AGENT (Task 11,
2026-09-26) from every row of the three rule catalogs and awaits the owner's
verification -- the spec wants a person to write it once; until one has read
it, it is a proposal a test holds still, not a person's mapping.

Gate 1 (the 48-row CV sheet), the 77-sentence letter sheet and the negation
check call a real provider and carry the `live` marker, so
`addopts = "-m 'not live'"` keeps them out of a default run; select them with
`-m live`. Each also skips when the decision route has no key, so a live run
without one reports skipped rather than a crash. All three run the production
path (derive.candidates + derive._grammar_rules + the rule_sinks projection),
so they measure what ships.

Gate 1 is partly train-on-test, and that is recorded here rather than left for
someone to discover by reading `grammar_values.py::_format_examples`. 14 of
the 48 rows (8 `standard` rows -> `any`, 6 `none` rows -> `not_a_format_rule`
-- verified by counting `FORMAT_EXAMPLES`'s examples) are copied verbatim into
the format-decision prompt as few-shot examples, so the model has effectively
memorised them before the gate ever asks about them. The unseen bar the >= 46/48
threshold actually sets is therefore closer to >= 32/34 on the 34 rows the
prompt never quotes. `_format_examples()` selects on `sentence` and `outcome`
only -- the `strength` column (fix round 1's own C10 addition, required vs.
preferred on the europass rows) must never be read there, because doing so
would let the gate's own scoring hint leak into the prompt it is grading.
"""

import csv
import pathlib
from collections import defaultdict

import pytest

from apps.documents.constraints import (
    _INCLUDE_TARGETS,
    _ORDER_DIRECTIONS,
    _ORDER_TARGETS,
    _SECTIONS,
)
from apps.documents.grammar import (
    BOUNDS,
    DOCUMENTS,
    FORM_VALUES,
    FORMAT_VERDICTS,
    NAMING_VALUES,
    OPERATIONS,
    STYLE_VALUES,
    UNITS,
    limit_sink,
    sink_for,
)

_DOCS = pathlib.Path(__file__).resolve().parents[2] / "docs" / "research"
_MAP = _DOCS / "rule-grammar-map.csv"
_CATALOGS = {
    "cv-rules": _DOCS / "cv-rules.csv",
    "cv-style-rules": _DOCS / "cv-style-rules.csv",
    "letter-rules": _DOCS / "letter-rules.csv",
}

#: Why a row carries no operation. Closed, so a note cannot drift into prose
#: that hides a missing operation. `unapplied:` is the one reason that is a
#: page requirement the engine cannot act on (spec §6.5) and is what the
#: catalogue-coverage check counts; the rest are rules no page states as a
#: requirement of this document.
_OTHER_REASONS = (
    "not a page rule:",  # engine design, research record, house style, reader evidence
    "writing quality:",  # a convention the generator's prompt carries
    "not a requirement:",  # a sanction or eligibility consequence, nothing to type
    "another document:",  # document=other binds nothing by design (grammar.sink_for)
    "page fact:",  # carried by grammar_questions.read_page_facts, not an operation
    "unapplied:",  # a page requirement nothing here can carry: shown and counted
)
#: The two reasons that say no page states the rule as a requirement at all.
_NOT_PAGE_STATED = ("not a page rule:", "writing quality:")


def _mapped() -> list[dict[str, str]]:
    with _MAP.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _catalog_ids() -> dict[str, set[str]]:
    ids = {}
    for catalog, path in _CATALOGS.items():
        with path.open(encoding="utf-8") as handle:
            ids[catalog] = {row["ID"] for row in csv.DictReader(handle)}
    return ids


def _value(row: dict[str, str]) -> object:
    """The map's value as the grammar holds it: an order is a (target,
    direction) pair, written `target:direction` in the sheet."""
    if row["operation"] == "order":
        return tuple(row["value"].split(":", 1))
    return row["value"]


def _sink(row: dict[str, str]) -> str:
    if row["operation"] == "limit":
        return limit_sink(row["document"], row["bound"], row["value"])
    return sink_for(row["document"], row["operation"], _value(row))


def test_every_catalogued_rule_is_in_the_map():
    """Gate 7. A rule in the catalogs with no line here is a rule nobody
    checked the grammar against -- and a line naming no real rule is noise."""
    mapped = _mapped()
    ids = _catalog_ids()
    for catalog, catalogued in ids.items():
        missing = catalogued - {row["rule_id"] for row in mapped if row["catalog"] == catalog}
        assert not missing, f"{catalog}: {len(missing)} unmapped rules, e.g. {sorted(missing)[:5]}"
    for row in mapped:
        assert row["rule_id"] in ids.get(row["catalog"], set()), row


def test_every_mapped_slot_is_in_a_closed_list():
    closed: dict[str, tuple[object, ...]] = {
        "style": STYLE_VALUES, "form": FORM_VALUES, "naming": NAMING_VALUES,
        "format": FORMAT_VERDICTS, "include": _INCLUDE_TARGETS, "emphasise": _SECTIONS,
        "limit": UNITS,
        "order": tuple((t, d) for t in _ORDER_TARGETS for d in _ORDER_DIRECTIONS),
    }
    for row in _mapped():
        assert row["document"] in DOCUMENTS, row
        assert row["operation"] in OPERATIONS, row
        if row["operation"] in closed:
            assert _value(row) in closed[row["operation"]], row
        if row["operation"] == "limit":
            assert row["bound"] in BOUNDS, row
        else:
            assert not row["bound"], row


def test_every_mapped_rule_reaches_a_sink_or_says_why_not():
    """An `other` row is legitimate when it names its reason from a closed list;
    a silent one is a missing operation wearing a disguise. A typed row whose
    value has no sink must say `unapplied:` -- and a row that does reach a sink
    must not, so the note cannot go stale when a sink is added."""
    for row in _mapped():
        note = row["note"].strip()
        if row["operation"] == "other":
            assert note.startswith(_OTHER_REASONS), f"{row['rule_id']}: `other` needs a reason"
            continue
        sink = _sink(row)
        if sink:
            assert not note.startswith("unapplied:"), f"{row['rule_id']} reaches {sink}"
        else:
            assert note.startswith("unapplied:"), (
                f"{row['rule_id']} maps to {row['operation']}={row['value']} with no sink"
            )


def test_the_catalogue_coverage_check(capsys):
    """Not §11 gate 8 -- that one is `other` on <= 2% of the labelled corpus's
    requirement SENTENCES and needs the corpus. This is its static cousin over
    the catalogs (controller ruling C21): of the rows that ARE page-stated
    requirements, at most a fifth may be ones nothing here can carry. The raw
    share of rules with no operation at all is printed, because most of it is
    writing-quality convention and research record no page states."""
    rows = _mapped()
    stated = [r for r in rows if not r["note"].startswith(_NOT_PAGE_STATED)]
    unapplied = [r for r in stated if r["note"].startswith("unapplied:")]
    by_rule: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_rule[row["rule_id"]].append(row)
    no_operation = [k for k, v in by_rule.items() if all(r["operation"] == "other" for r in v)]
    with capsys.disabled():
        print(f"\ncatalogue coverage: {len(unapplied)} of {len(stated)} page-stated rows "
              f"unapplied {sorted({r['rule_id'] for r in unapplied})}; "
              f"{len(no_operation)} of {len(by_rule)} rules have no operation at all")
    assert len(unapplied) / len(stated) <= 0.2


# --- Live: the decision route must have a key ------------------------------------

@pytest.fixture
def decision_route():
    """Skip, never crash, when the route has no key: the paid runs need the
    owner's go-ahead and a key this environment may not hold."""
    from apps.research.decisions import _decisions_key

    name, key = _decisions_key()
    if not key:
        pytest.skip(f"{name} is not set; the live gates need the decision route")


# --- Gate 1: the 48 CV sentences, scored on the sheet's own outcomes -------------

def _europass(rules) -> str:
    """The applied Europass verdict on one sentence, or ""."""
    for rule in rules:
        if (rule.document == "cv" and rule.applied and rule.operation == "format"
                and str(rule.value).startswith("europass")):
            return str(rule.value)
    return ""


def _europass_wrong(outcome: str, strength: str, rules) -> bool:
    """The Europass reading is wrong -- the one outcome scored wrong on every
    row, because it is what moves a student's data to europa.eu (C10).

    Wrong three ways: Europass where the sheet says none, none where the sheet
    says Europass, and a mandate where the sheet says the page only recommends
    it. The last is never a near miss: "we recommend Europass" read as
    `europass_required` is how a recommendation became a mandate (the keyword
    rule's 61%, spec of 2026-09-13). A mandate read as `europass_preferred`
    still renders Europass, so the action is right and it is not counted here.
    """
    verdict = _europass(rules)
    if outcome != "europass":
        return bool(verdict)
    if not verdict:
        return True
    return strength == "preferred" and verdict == "europass_required"


def _same_value(got: object, expected: str) -> bool:
    if isinstance(got, list):
        got = ",".join(got)
    try:
        return float(got) == float(expected)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(got).lower() == expected.lower()


def _cv_score(row: dict[str, str], rules) -> str:
    """"correct" / "undecided" / "wrong" for one row, from the rules on its sentence.

    The sheet's outcomes are actions (europass / standard), constraints,
    directives, `unapplied` and `none` -- the scoring the frontier gate uses
    (tests/documents/test_derive.py::_classify), read off typed rules.
    """
    from apps.documents.rule_sinks import to_constraint_rules, to_directives

    expect, detail = row["outcome"], row["detail"]
    if _europass_wrong(expect, row["strength"], rules):
        return "wrong"
    cv = [r for r in rules if r.document == "cv"]
    noted = any(not r.applied for r in cv)
    if expect == "europass":
        return "correct"
    constraints = {c.key: c.value for c in to_constraint_rules(cv, source_url="")}
    directives = {(d["action"], d["target"], d["value"])
                  for d in to_directives(cv, source_url="")}
    if expect == "standard":
        stated = any(r.applied and r.operation == "format" and r.value == "any" for r in cv)
        return "correct" if stated else "undecided" if noted else "wrong"
    if expect == "none":
        # A constraint or directive on somebody else's CV, or on a question, is
        # a wrong attribution to the applicant's own (swiss-3rd).
        return "wrong" if constraints or directives else "correct"
    if expect == "unapplied":
        return "correct" if any(r.note == "unapplied" for r in cv) else "undecided"
    if expect == "constraint":
        key, _, value = detail.partition("=")
        if key in constraints:
            return "correct" if _same_value(constraints[key], value) else "wrong"
    elif expect == "order":
        target, _, direction = detail.partition("=")
        if ("order", target, direction) in directives:
            return "correct"
    elif (expect, detail, None) in directives:
        return "correct"
    return "undecided" if noted else "wrong"


@pytest.mark.live
@pytest.mark.django_db
def test_the_forty_eight_row_cv_gate(decision_route, capsys):
    """Gate 1 (spec §11.1): no wrong Europass reading on any of the 48 rows,
    and >= 46/48 correct overall. The Europass reading matters more than the
    rest because it is what moves student data."""
    from apps.documents.derive import _grammar_rules, candidates

    with (_DOCS / "cv-format-eval.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 48
    found = candidates("\n".join(r["sentence"] for r in rows), ())
    assert [c.text for c in found] == [r["sentence"] for r in rows], (
        "every eval sentence must be a candidate by code, in order"
    )
    rules, _ = _grammar_rules(found, language="", budget=None, client=None, record=False)
    by_index = defaultdict(list)
    for rule in rules:
        by_index[rule.index].append(rule)

    scored = {row["id"]: _cv_score(row, by_index[i]) for i, row in enumerate(rows)}
    europass_wrong = [
        row["id"] for i, row in enumerate(rows)
        if _europass_wrong(row["outcome"], row["strength"], by_index[i])
    ]
    correct = sum(v == "correct" for v in scored.values())
    with capsys.disabled():
        print(f"\ncv gate: {correct}/48 correct; europass wrong {europass_wrong}; "
              f"not correct {[(k, v) for k, v in scored.items() if v != 'correct']}")
    assert europass_wrong == [], f"{len(europass_wrong)} of 48 wrong on Europass"
    assert correct >= 46


# --- The 77 letter sentences, scored per figure (addendum §1, §6.1) ---------------

# <!-- reconciled 2026-09-26: min_chars is a length field since Task 4 Part A -->
_LENGTH_FIELDS = ("max_words", "min_words", "max_chars", "min_chars", "max_pages")


def _same(field: str, got: object, expected: str) -> bool:
    if field in ("signed_declaration", "handwritten"):
        return got is True and expected == "true"
    if field in ("max_pages", "line_spacing", "margins_cm"):
        return float(got) == float(expected)  # type: ignore[arg-type]
    # <!-- reconciled 2026-09-26 -->
    if field in ("max_words", "min_words", "max_chars", "min_chars", "font_min_pt"):
        return int(got) == int(expected)  # type: ignore[call-overload]
    return str(got).lower() == expected.lower()


@pytest.mark.live
@pytest.mark.django_db
def test_the_seventy_seven_sentence_letter_gate(decision_route, capsys):
    """Every figure is its own decision, so a row is scored on its figure:
    asserted when a rule on its sentence projects to the expected field and
    value, contradicted when one projects to that field with another value --
    or, for a floor, when the floor's figure comes back as the cap, the defect
    the per-figure questions exist to close.

    The bar is the frontier judge's measured one (addendum §1): no wrong cap
    and no missed naming=forbidden in any language, and English asserting at
    least the 51 rules the frontier asserted. A `none` row is printed, never
    asserted, as tests/documents/test_letter_derive.py does. A row whose
    sentence is not a candidate is a result about the vocabulary, counted and
    printed (six of the 77 on 2026-09-26, measured offline).
    """
    from apps.documents.derive import _grammar_rules, candidates
    from apps.documents.rule_sinks import letter_field
    from apps.research.decisions import DecisionBudget

    # <!-- amended 2026-09-26: addendum §7 -- the cost is measured, not assumed. An
    # unlimited budget counts every input token the grammar spends on these sentences. -->
    spend = DecisionBudget()
    with (_DOCS / "letter-shape-eval.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 77
    by_language: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_language[row["language"]].append(row)

    wrong_caps: list[tuple[str, str, str]] = []
    missed_forbidden: list[str] = []
    asserted_by_language: dict[str, int] = {}
    for language, group in sorted(by_language.items()):
        found = candidates("\n".join(r["sentence"] for r in group), (), language=language)
        index_of = {c.text: i for i, c in enumerate(found)}
        rules, _ = _grammar_rules(found, language=language, budget=spend, client=None,
                                  record=False)
        landed: dict[int, list[tuple[str, object]]] = defaultdict(list)
        for rule in rules:
            target = letter_field(rule)
            if target is not None:
                landed[rule.index].append(target)
        asserted = missed = contradicted = unfound = printed = 0
        for row in group:
            index = index_of.get(row["sentence"])
            if index is None:
                unfound += 1
                continue
            field, expected = row["expected_field"], row["expected_value"]
            got = landed[index]
            if field == "none":
                printed += 1
                with capsys.disabled():
                    print(f"  ? {row['id']} [{language}] untypeable -> {got}")
                continue
            same = [value for name, value in got if name == field]
            floor_as_cap = field.startswith("min_") and any(
                name == "max_" + field[4:] and _same(field, value, expected)
                for name, value in got
            )
            if floor_as_cap or any(not _same(field, value, expected) for value in same):
                contradicted += 1
                if field in _LENGTH_FIELDS:
                    wrong_caps.append((row["id"], language, field))
            elif same:
                asserted += 1
            else:
                missed += 1
                if field == "naming" and expected == "forbidden":
                    missed_forbidden.append(row["id"])
        asserted_by_language[language] = asserted
        with capsys.disabled():
            print(f"  {language}: {len(group)} rows, {asserted} asserted, {missed} missed, "
                  f"{contradicted} contradicted, {unfound} not a candidate, "
                  f"{printed} untypeable")
    assert wrong_caps == []
    assert missed_forbidden == []
    assert asserted_by_language.get("en", 0) >= 51, asserted_by_language
    # Addendum §7: a page costing more than 3x the estimate fails the gate. The design's
    # §10 prices the rule judgement at ~$0.0002 per page, ~4,800 input tokens at Jev's
    # $0.042/M, over ~10 requirement sentences: ~500 tokens a sentence, so the bar is
    # 1,500. Printed every run so a drift upward is visible before it fails.
    per_sentence = spend.spent / len(rows)
    with capsys.disabled():
        print(f"  cost: {spend.spent} input tokens, {per_sentence:.0f} per sentence")
    assert per_sentence <= 1_500, per_sentence


# <!-- review focus 2 --> Jev's own documentation names literal reading of negation as a
# weakness (jev-1.13 failure-mode page). No stub can show how Jev reads these, so they are
# live: a negated maximum, a negated minimum, and a sentence stating there is no limit.
#
# <!-- fix round 1, finding 2 --> "The statement should not be less than 300 words." is not
# a candidate by code (candidates() finds 0 -- it names no document, so nothing marks it
# `letter=True`), which would have failed this test on its first live run before the model
# was ever asked. "Your motivation letter..." is: verified offline, one candidate, by
# test_every_negation_sentence_is_a_candidate_by_code below.
_NEGATIONS = (
    ("Your motivation letter must be no more than 500 words.", "en", "max_words", 500),
    ("Your motivation letter should not be less than 300 words.", "en", "min_words", 300),
    ("Das Motivationsschreiben darf nicht länger als zwei Seiten sein.", "de", "max_pages", 2),
    ("There is no word limit for the motivation letter.", "en", None, None),
)


def test_every_negation_sentence_is_a_candidate_by_code():
    """Offline half of fix round 1, finding 2: a live gate that spends real
    money must not learn on its first paid run that its own fixture is not a
    candidate. `candidates()` needs no model and no database, so this runs in
    every default test session, not just `-m live`."""
    from apps.documents.derive import candidates

    for sentence, language, _field, _expected in _NEGATIONS:
        found = candidates(sentence, (), language=language)
        assert len(found) == 1, f"not exactly one candidate by code: {sentence!r} -> {found}"


@pytest.mark.live
@pytest.mark.django_db
def test_negated_limits_read_the_right_way_round(decision_route, capsys):
    from apps.documents.derive import _grammar_rules, candidates
    from apps.documents.rule_sinks import letter_field

    for sentence, language, field, expected in _NEGATIONS:
        found = candidates(sentence, (), language=language)
        assert found, f"not a candidate by code: {sentence!r}"
        rules, _ = _grammar_rules(found, language=language, budget=None, client=None,
                                  record=False)
        landed = [target for rule in rules if (target := letter_field(rule)) is not None]
        with capsys.disabled():
            print(f"  {sentence!r} -> {landed}")
        lengths = [(name, value) for name, value in landed if name in _LENGTH_FIELDS]
        if field is None:
            assert lengths == [], sentence  # "no word limit" sets no limit
        else:
            assert lengths == [(field, expected)], sentence
