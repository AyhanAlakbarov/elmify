import re
from datetime import date
from pathlib import Path

import pytest
from babel import Locale

from apps.research.candidates.who import find_places
from apps.research.card_funding.groups import expand, group_of, rows

#: Babel's territory codes include these non-countries; a list row may not use one.
_NOT_COUNTRIES = {"EU", "EZ", "UN", "QO", "ZZ"}
ON = date(2026, 10, 13)

SOURCES = Path(__file__).parent / "sources"

# Counts and memberships as each source states them, checked by hand on 2026-10-12/13 (plan 2b,
# Task 1): the DAC PDF lists 141 recipients; M49 flags 44 LDCs and puts 53 rows in region 202,
# Sudan in Northern Africa (015); the World Bank API classifies 25 L + 47 LM + 59 UM economies.
COUNTS = {"DAC": 141, "LDC": 44, "SSA": 54, "LMY": 131, "CIS": 10}


def test_every_code_is_a_country_and_every_row_cites_its_source():
    territories = {code for code in Locale("en").territories if len(code) == 2}
    for row in rows():
        assert row.codes and row.codes <= territories - _NOT_COUNTRIES, row.group
        assert row.source.startswith(("https://", "docs/")), row.group
        date.fromisoformat(row.as_of)
        assert row.status in {"eligible", "held"}, row.group


def test_each_group_has_the_count_its_source_states():
    for group, count in COUNTS.items():
        assert len(set().union(*(r.codes for r in rows() if r.group == group))) == count, group


def test_memberships_the_research_checked_on_the_sources():
    dac = expand("DAC", on=ON)
    assert {"AZ", "AM", "BY", "GE", "KZ", "KG", "MD", "TJ", "TM", "TR", "UA", "UZ"} <= dac.eligible
    assert "RU" not in dac.eligible
    ssa = expand("SSA", on=ON)
    assert ssa.held == {"SD", "DJ"} and "SD" not in ssa.eligible and "KE" in ssa.eligible
    assert {"KI", "SB", "TV", "HT"} <= expand("LDC", on=ON).eligible
    assert expand("LDC", on=ON).eligible <= dac.eligible  # the DAC PDF's own LDC column


def test_cis_follows_the_owners_table():
    cis = expand("CIS", on=ON)
    assert cis.eligible == {"AZ", "AM", "BY", "KZ", "KG", "TJ", "TM", "UZ", "MD"}
    assert cis.held == {"UA"} and "GE" not in cis.eligible | cis.held
    after = expand("CIS", on=date(2027, 4, 8))
    assert "MD" in after.held and "MD" not in after.eligible


def test_developing_is_held_on_the_dac_list_and_out_off_it():
    developing = expand("DEVELOPING", on=ON)
    assert developing.eligible == set() and "AZ" in developing.held and "RU" not in developing.held
    assert expand("DEVELOPING", on=ON, page_says_dac=True).eligible == expand("DAC", on=ON).eligible


def test_vague_groups_hold_everyone_and_lmy_needs_to_be_the_whole_criterion():
    for group in ("GLOBAL_SOUTH", "EMERGING", "NEWLY_INDUSTRIALISED", "LMIC"):
        assert expand(group, on=ON).everyone_held, group
    assert expand("LMY", on=ON).everyone_held
    assert "AZ" in expand("LMY", on=ON, sole_criterion=True).eligible
    assert expand("INTERNATIONAL", on=ON) is None
    assert expand("EU", on=ON).eligible >= {"DE", "FR"}


@pytest.mark.parametrize(("line", "group"), [
    ("Open to citizens of developing countries.", "DEVELOPING"),
    ("for applicants from development and newly industrialised countries", "DEVELOPING"),
    ("граждане государств-участников СНГ", "CIS"),
    ("students from the Global South", "GLOBAL_SOUTH"),
    ("nationals of low- and middle-income countries", "LMY"),
    ("Applicants from LMICs only", "LMIC"),
    ("citizens of sub-Saharan Africa", "SSA"),
    ("least developed countries (LDCs)", "LDC"),
    ("countries on the DAC list", "DAC"),
    ("emerging economies", "EMERGING"),
    ("open to international students", "INTERNATIONAL"),
    ("citizens of OIC member states", "OIC"),
    ("منح لطلاب منظمة التعاون الإسلامي", "OIC"),
    ("open to Turkic States nationals", "TURKIC_STATES"),
])
def test_each_phrase_is_a_place_candidate_naming_its_group(line, group):
    groups = [group_of(p.text) for p in find_places(line) if p.kind == "unknown_group"]
    assert groups == [group], (line, [p.text for p in find_places(line)])


def test_oic_and_turkic_states_expand_via_regions():
    oic = expand("OIC", on=ON)
    assert oic is not None and {"AZ", "TR", "SA", "ID", "MY", "PK", "KZ", "UZ"} <= oic.eligible
    turkic = expand("TURKIC_STATES", on=ON)
    assert turkic is not None and turkic.eligible == {"AZ", "KG", "KZ", "TR", "UZ"}


# --- each list against its raw source snapshot (tests/research/card_funding/sources) -----------
# A snapshot starts with its URL and fetch date; the test compares the source's ISO2 set to the
# CSV, so a mistyped code that keeps the count still fails.


def _snapshot(name):
    lines = (SOURCES / name).read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# https://") and "fetched 20" in lines[0], name
    return [line.split("\t") for line in lines if not line.startswith("#")]


def _csv(group):
    return set().union(*(r.codes for r in rows() if r.group == group))


#: Names the DAC PDF prints that Babel spells differently.
_DAC_ALIASES = {
    "China (People's Republic of)": "CN", "Congo": "CG", "Democratic Republic of the Congo": "CD",
    "Democratic People's Republic of Korea": "KP", "Côte d'Ivoire": "CI", "Cabo Verde": "CV",
    "Iran": "IR", "Kosovo": "XK", "Lao People's Democratic Republic": "LA", "Micronesia": "FM",
    "Moldova": "MD", "Syrian Arab Republic": "SY", "Tanzania": "TZ", "Türkiye": "TR",
    "Viet Nam": "VN", "West Bank and Gaza Strip": "PS", "Timor-Leste": "TL", "Eswatini": "SZ",
    "Wallis and Futuna": "WF", "Tokelau": "TK", "Niue": "NU", "Saint Helena": "SH",
    "Venezuela": "VE", "São Tomé and Príncipe": "ST", "Bosnia and Herzegovina": "BA",
    "Myanmar": "MM", "Saint Lucia": "LC", "Saint Vincent and the Grenadines": "VC",
    "Bolivia": "BO", "Gambia": "GM", "Montserrat": "MS", "Nauru": "NR",
}


def test_dac_matches_the_oecd_pdf_names():
    by_name = {n: c for c, n in Locale("en").territories.items() if len(c) == 2}
    codes = set()
    for (raw,) in _snapshot("dac_raw.txt"):
        name = re.sub(r"\s*\((?:L|LM|UM|H)\)$", "", raw.replace("\u2019", "'"))
        name = name.rstrip("*0123456789")
        codes.add(_DAC_ALIASES.get(name) or by_name[name])
    assert len(codes) == 141
    assert codes == _csv("DAC")


def test_ldc_and_sub_saharan_africa_match_the_m49_table():
    table = _snapshot("m49.tsv")
    assert {r[0] for r in table if r[4] == "LDC"} == _csv("LDC")
    # M49 region 202 puts Sudan in Northern Africa; the owner's table holds it (plan 2b, Task 1).
    assert {r[0] for r in table if r[2] == "202"} | {"SD"} == _csv("SSA")


def test_lmy_is_the_world_banks_low_lower_and_upper_middle_income_economies():
    table = _snapshot("worldbank.tsv")
    assert {r[0] for r in table if r[3] in {"LIC", "LMC", "UMC"}} == _csv("LMY")


def test_the_two_dated_memberships_flip_on_their_date():
    assert "MD" in expand("CIS", on=date(2027, 4, 7)).eligible
    assert "MD" in expand("CIS", on=date(2027, 4, 8)).held
    assert "NR" in expand("DAC", on=date(2026, 12, 31)).eligible
    after = expand("DAC", on=date(2027, 1, 1))
    assert "NR" in after.held and "NR" not in after.eligible
