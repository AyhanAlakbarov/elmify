import csv
from pathlib import Path

from apps.documents.letter_defaults import (
    COUNTRY_SYSTEM,
    MODE_DEFAULTS,
    SYSTEM_DEFAULTS,
    defaults_for,
)

_RULES = Path("docs/research/letter-shape-rules.csv")
_MAP = Path("docs/research/letter-shape-country-map.csv")
#: Only the countries this test needs to cross-check; the map names countries
#: in English prose, and a full name-to-ISO table is not this test's job.
_COUNTRY_CODES = {
    "Germany": "DE", "Austria": "AT", "Switzerland": "CH", "France": "FR",
    "Spain": "ES", "Portugal": "PT", "Japan": "JP", "South Korea": "KR",
    "Turkey": "TR", "United Kingdom": "GB", "Netherlands": "NL", "Italy": "IT",
}


def _known_rule_ids() -> set[str]:
    with _RULES.open(encoding="utf-8", newline="") as handle:
        return {row["ID"] for row in csv.DictReader(handle)}


def _tag_by_rule_id() -> dict[str, str]:
    with _RULES.open(encoding="utf-8", newline="") as handle:
        return {row["ID"]: row["Applies to"] for row in csv.DictReader(handle)}


def test_every_default_row_cites_an_existing_rule() -> None:
    known = _known_rule_ids()
    for key, row in {**SYSTEM_DEFAULTS, **MODE_DEFAULTS}.items():
        assert row.rules, key
        assert set(row.rules) <= known, (key, set(row.rules) - known)


def test_a_row_only_claims_a_position_when_a_cited_rule_states_one() -> None:
    """What this enforces: a row with a non-empty `opening` or `closing` must cite
    at least one rule the research CSV tags `opening` or `order`. It fails a row
    whose *only* citations are tagged `proportion` (length), `personalisation`
    (content) or `formalities` -- none of which says where anything goes -- which
    is the coarse half of a defect three human reviews caught by hand.

    What this does NOT enforce, measured rather than assumed: a rule tagged
    `opening`/`order` whose TEXT establishes no sequence still satisfies this
    check. M-072 is tagged `order` though its text only says the statement must
    address "at least three" of four unordered questions -- the portfolio-led
    row this test was written to catch cited exactly that id, and would have
    passed. M-002 (System D) is tagged `order` though its own text says "Not all
    of the above questions have to be addressed!", i.e. it disclaims an order --
    and D's pre-fix citations already included it, so this test would not have
    caught that defect either. A tag on the CSV marks a rule's TOPIC, not
    whether its text mandates a sequence, and no text-matching heuristic can
    safely stand in for reading it: M-002's own sentence contains the phrase
    "not an order", which a keyword search would score as positional evidence
    for the opposite of what it says.

    Why it is kept anyway: it closes the coarse case -- a row citing nothing
    positional at all -- permanently and for free, even though it is not the
    check that found any of the three defects above.

    What still requires a person: reading the cited rule's actual sentence
    against the position the row claims. That reading, not this test, is what
    caught all three findings it was written to guard against."""
    position_tags = {"opening", "order"}
    tag_by_id = _tag_by_rule_id()
    for key, row in {**SYSTEM_DEFAULTS, **MODE_DEFAULTS}.items():
        if not (row.opening or row.closing):
            continue
        cited_tags = {tag_by_id.get(rule_id) for rule_id in row.rules}
        assert cited_tags & position_tags, (key, row.rules, cited_tags)


def test_every_assigned_system_is_a_real_one() -> None:
    """Pre-flight ruling 5: A-F, and every assignment matches at least one map row.

    A country the map covers more than once (one row per institution or scheme)
    must not be asserted against every row -- that is unsatisfiable for any
    multi-row country, which §10 says is common. It is enough that the assigned
    system matches ONE of the country's rows -- the university-admission one,
    since a funder's own system is resolved before this table is ever read
    (see letter_defaults.py's module docstring).
    """
    assert set(COUNTRY_SYSTEM.values()) <= set("ABCDEF")
    systems_by_country: dict[str, set[str]] = {}
    with _MAP.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            country, system = row["Country"].strip(), row["System"].strip()[:1]
            code = _COUNTRY_CODES.get(country)
            if code and system:
                systems_by_country.setdefault(code, set()).add(system)
    for code, assigned in COUNTRY_SYSTEM.items():
        if code in systems_by_country:
            assert assigned in systems_by_country[code], (code, assigned, systems_by_country[code])


def test_an_unmapped_country_takes_the_shape_that_breaks_no_rule_anywhere() -> None:
    """Spec §5: system B's plain essay, and the resolution is logged."""
    row = defaults_for(
        country_code="ZZ", track="taught", portfolio_led=False,
        funder_kind="UNIVERSITY_ADMISSION",
    )
    assert row.form == "ESSAY" and row.archetypes


def test_a_funder_kind_overrides_the_country() -> None:
    """A scholarship's own system overrides the country's university system --

    and it is each scholarship's own country-map row, not automatically Germany's
    DAAD shape: Japan's MEXT and South Korea's GKS are System E, not D.
    """
    german = defaults_for(
        country_code="DE", track="taught", portfolio_led=False,
        funder_kind="GOVERNMENT_SCHOLARSHIP",
    )
    japanese = defaults_for(
        country_code="JP", track="taught", portfolio_led=False,
        funder_kind="GOVERNMENT_SCHOLARSHIP",
    )
    korean = defaults_for(
        country_code="KR", track="taught", portfolio_led=False,
        funder_kind="GOVERNMENT_SCHOLARSHIP",
    )
    # Germany has no documented scheme system of its own, so it falls back to D
    # (the DAAD shape) -- which still overrides its university system, A.
    assert german.archetypes == SYSTEM_DEFAULTS["D"].archetypes
    # Japan and South Korea's own scheme rows name System E, not D.
    assert japanese.archetypes == SYSTEM_DEFAULTS["E"].archetypes
    assert korean.archetypes == SYSTEM_DEFAULTS["E"].archetypes
    assert japanese.archetypes != german.archetypes


def test_france_defaults_to_a_formal_letter_and_the_uk_does_not() -> None:
    france = defaults_for(
        country_code="FR", track="taught", portfolio_led=False,
        funder_kind="UNIVERSITY_ADMISSION",
    )
    uk = defaults_for(
        country_code="GB", track="taught", portfolio_led=False,
        funder_kind="UNIVERSITY_ADMISSION",
    )
    assert france.form == "FORMAL_LETTER" and uk.form == "ESSAY"
    # France resolves to System A (its university row); the archetypes are still
    # System A's, not System B's plain-Anglosphere fallback. The opening is NOT
    # System A's any more (fix round 2, finding 2): M-026 is France-specific
    # evidence that used to be asserted for all of System A -- Germany, the
    # Netherlands, Sweden and the rest -- and now applies only to France, via
    # `_COUNTRY_OPENING`.
    system_a = SYSTEM_DEFAULTS["A"]
    assert france.archetypes == system_a.archetypes
    assert france.opening != system_a.opening
    assert "diploma" in france.opening


def test_a_research_track_opens_on_the_research_position() -> None:
    row = defaults_for(
        country_code="GB", track="research", portfolio_led=False,
        funder_kind="UNIVERSITY_ADMISSION",
    )
    assert "RESEARCH_PLAN" in row.archetypes
