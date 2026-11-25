"""Tests for compiling and seeding all researched CV, CV-style, and letter rules."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import get_args

import pytest
from django.core.validators import URLValidator

from apps.documents.catalog_seed import (
    _CURATED_SEED_RULES,
    SEED_FUNDERS,
    SEED_RULES,
    _assert_no_same_scope_conflict,
    compile_csv_seed_rules,
    seed_catalog_constraints,
    seed_cv_rules,
)
from apps.documents.constraints import (
    _CONSTRAINT_KEYS,
    QUOTE_MAX_CHARS,
    Enforcement,
    resolve_rules,
)
from apps.documents.render import _CHECKERS, _CONTENT_ONLY_KEYS
from apps.documents.requirement_list import _fits, build_requirements
from apps.funding.models import CatalogRule, FundingOpportunity, Institution, Program

pytestmark = pytest.mark.django_db

_RESEARCH_DIR = Path(__file__).resolve().parents[2] / "docs" / "research"
_URL_RE = re.compile(r"https://[^\s;\]\"]+")


def _seed_all_funders() -> None:
    for canonical_key, name, _requirement in SEED_FUNDERS:
        FundingOpportunity.objects.update_or_create(
            canonical_key=canonical_key,
            defaults={
                "name": name,
                "family": "GOVERNMENT_SCHOLARSHIP",
                "scope_type": "GLOBAL",
            },
        )


def _programme(country_code: str = "GB", institution_key: str = "") -> Program:
    inst_key = institution_key or f"inst:{country_code.lower()}"
    institution, _ = Institution.objects.update_or_create(
        canonical_key=inst_key,
        defaults={
            "name": f"University ({inst_key})",
            "country_code": country_code,
            "official_website": "https://university.example.test",
        },
    )
    program, _ = Program.objects.update_or_create(
        canonical_key=f"prog:{inst_key}",
        defaults={
            "institution": institution,
            "name": "MSc Test Programme",
            "campus_name": "Main",
            "city": "City",
            "country_code": country_code,
            "location_key": f"{country_code.lower()}:city",
            "degree_level": "MASTER",
            "teaching_languages": ["English"],
            "duration_months": 24,
        },
    )
    return program


def _taught_content():
    from tests.documents.test_render import _content

    return _content()


@pytest.mark.parametrize(
    ("csv_filename", "expected_https_count"),
    [
        ("cv-rules.csv", 56),
        ("cv-style-rules.csv", 50),
        ("letter-rules.csv", 69),
    ],
)
def test_every_https_backed_csv_row_is_compiled_into_seed_rules(
    csv_filename: str, expected_https_count: int
) -> None:
    """Every row carrying an https:// URL in cv-rules.csv, cv-style-rules.csv,
    and letter-rules.csv must be present in SEED_RULES with an https:// URL."""
    with (_RESEARCH_DIR / csv_filename).open(newline="", encoding="utf-8") as handle:
        https_ids = {
            row["ID"].strip()
            for row in csv.DictReader(handle)
            if _URL_RE.search(row.get("Source URL [provenance]", ""))
        }
    assert len(https_ids) == expected_https_count

    seeded_by_id: dict[str, list[dict]] = {}
    for row in SEED_RULES:
        seeded_by_id.setdefault(row["rule_id"], []).append(row)

    missing = sorted(https_ids - set(seeded_by_id))
    assert not missing, f"{csv_filename} rows with https:// URL missing from SEED_RULES: {missing}"

    validate_url = URLValidator()
    for rule_id in sorted(https_ids):
        for entry in seeded_by_id[rule_id]:
            assert entry["source_url"].startswith("https://"), (
                f"{rule_id} has non-https source_url {entry['source_url']!r}"
            )
            validate_url(entry["source_url"])


def test_curated_seed_rules_remain_verbatim_in_seed_rules() -> None:
    """All original hand-curated rules must stay intact at the head of SEED_RULES."""
    assert SEED_RULES[: len(_CURATED_SEED_RULES)] == _CURATED_SEED_RULES
    compiled = compile_csv_seed_rules()
    assert len(compiled) >= 156
    assert len(SEED_RULES) == len(_CURATED_SEED_RULES) + len(compiled)


def test_every_seed_rule_satisfies_catalog_and_engine_invariants() -> None:
    """Every entry in SEED_RULES must satisfy schema, scope, key, and checker invariants."""
    allowed_keys = set(get_args(_CONSTRAINT_KEYS))
    valid_scopes = {"UNIVERSAL", "TRACK", "COUNTRY", "INSTITUTION", "FUNDER"}
    valid_enforcements = {"BINDING", "ADVISORY_HIGH_RISK", "ADVISORY_STYLE"}
    valid_confidences = {"high", "medium", "low"}
    funder_keys = {key for key, _name, _req in SEED_FUNDERS}

    _assert_no_same_scope_conflict(SEED_RULES)

    seen_pairs: set[tuple[str, str]] = set()
    for row in SEED_RULES:
        pair = (row["rule_id"], row["key"])
        assert pair not in seen_pairs, f"Duplicate (rule_id, key) pair: {pair}"
        seen_pairs.add(pair)

        assert re.match(r"^[RSCL]-\d{3}$", row["rule_id"]), row["rule_id"]
        assert row["scope_kind"] in valid_scopes, row["rule_id"]
        if row["scope_kind"] == "UNIVERSAL":
            assert row["scope_values"] == [], row["rule_id"]
        else:
            assert isinstance(row["scope_values"], list) and row["scope_values"], row["rule_id"]
        if row["scope_kind"] == "FUNDER":
            assert set(row["scope_values"]) <= funder_keys, (
                f"{row['rule_id']} names unseeded funders: {set(row['scope_values']) - funder_keys}"
            )

        assert row["key"] in allowed_keys, row["rule_id"]
        assert _fits(row["key"], row["value"]), (row["rule_id"], row["key"], row["value"])
        assert row["enforcement"] in valid_enforcements, row["rule_id"]
        if row["enforcement"] == "BINDING":
            assert row["key"] in _CHECKERS, row["rule_id"]
            if row["scope_kind"] in {"UNIVERSAL", "TRACK", "COUNTRY"}:
                assert row["key"] not in _CONTENT_ONLY_KEYS, row["rule_id"]

        assert 1 <= len(row["rule_text"]) <= QUOTE_MAX_CHARS, row["rule_id"]
        assert len(row["verified_for_cycle"]) <= 200, row["rule_id"]
        assert row["confidence"] in valid_confidences, row["rule_id"]


def test_seed_catalog_constraints_loads_all_rules_idempotently() -> None:
    """seed_cv_rules / seed_catalog_constraints seeds all SEED_RULES idempotently."""
    _seed_all_funders()
    created, updated, deleted = seed_catalog_constraints()
    assert created == len(SEED_RULES)
    assert updated == 0
    assert deleted == 0
    assert CatalogRule.objects.count() == len(SEED_RULES)

    assert seed_cv_rules() == (0, 0, 0)


def test_newly_seeded_countries_institutions_and_funders_resolve_rules() -> None:
    """Real caller check: resolve_rules and build_requirements consume the newly
    compiled CSV rules for previously unseeded countries, institutions, and funders."""
    _seed_all_funders()
    seed_cv_rules()
    content = _taught_content()
    catalog = tuple(CatalogRule.objects.order_by("rule_id"))

    # 1. Previously unseeded country rules: France (S-017) and Netherlands (S-018)
    fr_prog = _programme("FR")
    fr_rules = {r.key: (r.rule_id, r.value) for r in resolve_rules(fr_prog, None, content=content)}
    assert fr_rules["max_pages"] == ("S-017", 2)

    nl_prog = _programme("NL")
    nl_rules = {r.key: (r.rule_id, r.value) for r in resolve_rules(nl_prog, None, content=content)}
    assert nl_rules["max_pages"] == ("S-018", 2)

    # 2. Universal style rule S-022 (min_final_page_fill = 0.2)
    assert fr_rules["min_final_page_fill"] == ("S-022", 0.2)

    # 3. Newly seeded CV funder rules: DAAD PRIME (R-011), Swiss ESKAS (R-014, L-033),
    #    MemBioMed (R-004), Gates Cambridge (R-089, L-022)
    daad_prime = FundingOpportunity.objects.get(canonical_key="daad-prime")
    de_prog = _programme("DE")
    prime_rules = {
        r.key: (r.rule_id, r.value, r.enforcement)
        for r in resolve_rules(de_prog, daad_prime, content=content)
    }
    assert prime_rules["no_unexplained_gaps"] == ("R-011", 3, Enforcement.BINDING)

    eskas = FundingOpportunity.objects.get(canonical_key="swiss-eskas")
    ch_prog = _programme("CH")
    eskas_rules = {
        r.key: (r.rule_id, r.value, r.enforcement)
        for r in resolve_rules(ch_prog, eskas, content=content)
    }
    assert eskas_rules["cv_scope"] == ("R-014", "complete", Enforcement.BINDING)
    assert eskas_rules["max_pages"] == ("L-033", 2, Enforcement.BINDING)
    assert eskas_rules["language"] == ("L-033", ["en", "fr", "de", "it"], Enforcement.BINDING)

    membiomed = FundingOpportunity.objects.get(canonical_key="membiomed")
    mem_rules = {
        r.key: (r.rule_id, r.value, r.enforcement)
        for r in resolve_rules(fr_prog, membiomed, content=content)
    }
    assert mem_rules["required_fields"] == ("R-004", ["date_of_birth"], Enforcement.BINDING)

    gates = FundingOpportunity.objects.get(canonical_key="gates-cambridge")
    gb_prog = _programme("GB")
    gates_rules = {
        r.key: (r.rule_id, r.value, r.enforcement)
        for r in resolve_rules(gb_prog, gates, content=content)
    }
    assert gates_rules["ai_use_policy"] == ("R-089", "PROHIBITS", Enforcement.ADVISORY_HIGH_RISK)
    assert gates_rules["max_chars_incl_spaces"] == ("L-022", 3000, Enforcement.ADVISORY_STYLE)

    # 4. Newly seeded letter funder rules via build_requirements:
    #    CSC (L-008), MEXT (L-012, L-013), GKS (L-016), MAECI (L-036), Stipendium Hungaricum (L-031)
    csc = FundingOpportunity.objects.get(canonical_key="csc")
    csc_reqs = {
        i.key: (i.rule.rule_id, i.value)
        for i in build_requirements(_programme("CN"), csc, catalog=catalog).items
        if i.rule is not None and i.key != "unapplied"
    }
    assert csc_reqs["min_words"] == ("L-008", 800)
    assert csc_reqs["language"] == ("L-008", ["zh", "en"])

    mext = FundingOpportunity.objects.get(canonical_key="mext")
    mext_reqs = {
        i.key: (i.rule.rule_id, i.value)
        for i in build_requirements(_programme("JP"), mext, catalog=catalog).items
        if i.rule is not None and i.key != "unapplied"
    }
    assert mext_reqs["max_pages"] == ("L-012", 2)
    assert mext_reqs["language"] == ("L-012", ["ja", "en"])
    assert mext_reqs["ai_use_policy"] == ("L-013", "PROHIBITS")

    gks = FundingOpportunity.objects.get(canonical_key="gks")
    gks_reqs = {
        i.key: (i.rule.rule_id, i.value)
        for i in build_requirements(_programme("KR"), gks, catalog=catalog).items
        if i.rule is not None and i.key != "unapplied"
    }
    assert gks_reqs["max_chars_incl_spaces"] == ("L-016", 17000)

    maeci = FundingOpportunity.objects.get(canonical_key="maeci")
    maeci_reqs = {
        i.key: (i.rule.rule_id, i.value)
        for i in build_requirements(_programme("IT"), maeci, catalog=catalog).items
        if i.rule is not None and i.key != "unapplied"
    }
    assert maeci_reqs["max_words"] == ("L-036", 500)

    sh = FundingOpportunity.objects.get(canonical_key="stipendium-hungaricum")
    sh_reqs = {
        i.key: (i.rule.rule_id, i.value)
        for i in build_requirements(_programme("HU"), sh, catalog=catalog).items
        if i.rule is not None and i.key != "unapplied"
    }
    assert sh_reqs["font"] == ("L-031", "Times New Roman, 12 point")
    assert sh_reqs["language"] == ("L-031", ["en", "hu"])

    # 5. Newly seeded institution rules: UCL (L-038), KTH (L-053), Cornell (L-069)
    ucl_prog = _programme("GB", institution_key="gb:university college london")
    ucl_rules = {
        r.key: (r.rule_id, r.value) for r in resolve_rules(ucl_prog, None, content=content)
    }
    assert ucl_rules["max_chars_incl_spaces"] == ("L-038", 3000)
    assert ucl_rules["max_pages"] == ("L-038", 2)

    kth_prog = _programme("SE", institution_key="se:kth royal institute of technology")
    kth_rules = {
        r.key: (r.rule_id, r.value) for r in resolve_rules(kth_prog, None, content=content)
    }
    assert kth_rules["max_words"] == ("L-053", 500)
    assert kth_rules["language"] == ("L-053", "en")

    cornell_prog = _programme("US", institution_key="us:cornell university")
    cornell_rules = {
        r.key: (r.rule_id, r.value) for r in resolve_rules(cornell_prog, None, content=content)
    }
    assert cornell_rules["max_pages"] == ("L-069", 2)
