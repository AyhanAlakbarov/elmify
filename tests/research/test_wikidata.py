"""Wikidata as an enumerator (spec 6.2): the query's pins, the parser, the
bounds, and the CANDIDATE-only writer. And as the resolver's first stop (P856)
and the source of name variants (rule 4, spec 6.5): `find_item` and `sparql`.

tests/research/fixtures/wikidata_tr_university.json is hand-built from the
documented shape (SPARQL 1.1 JSON results: `head.vars`, `results.bindings[]`
of `{"type": "uri"|"literal", "value": ...}`), NOT a live capture: egress to
query.wikidata.org was blocked when this was written (2026-09-26); replace
with a trimmed live capture before trusting the parser. Its three QIDs are
illustrative, not asserted to be the universities' real items.
"""

import json
from pathlib import Path

import pytest
from django.utils import timezone

from apps.research import wikidata
from apps.research.models import Organisation, RegisterEntry
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db
FIXTURE = Path(__file__).parent / "fixtures" / "wikidata_tr_university.json"


def _row(**overrides: object):
    from apps.research.wikidata import EnumerationRow

    fields: dict[str, object] = dict(
        slug="wd_tr_university", country_code="TR", class_qid="Q3918", kind="INSTITUTION",
        widen=False, min_count=1, max_count=10, home_cells=("ANY",), host_cells=("TR",),
    )
    fields.update(overrides)
    return EnumerationRow(**fields)  # type: ignore[arg-type]


def test_the_query_pins_class_dissolution_and_website() -> None:
    from apps.research.wikidata import query_text

    text = query_text(_row())
    assert "wdt:P31 wd:Q3918" in text and "P279" not in text
    assert "FILTER NOT EXISTS { ?item wdt:P576 ?ended }" in text
    assert "wdt:P856 ?website" in text and 'wdt:P297 "TR"' in text
    assert "wdt:P31/wdt:P279* wd:Q3918" in query_text(_row(widen=True))


def test_the_query_refuses_anything_but_an_iso_code_and_a_qid() -> None:
    from apps.research.wikidata import query_text

    with pytest.raises(ValueError):
        query_text(_row(country_code='TR" } #'))
    with pytest.raises(ValueError):
        query_text(_row(class_qid="Q1 ; DROP"))


def test_the_recorded_response_parses_and_binds_candidates() -> None:
    from apps.research.wikidata import parse_bindings, record_items

    items = parse_bindings(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert items and all(item.qid.startswith("Q") and item.websites for item in items)
    report = record_items(_row(), items, now=timezone.now())
    assert report.bound == len(items)
    org = RegisterEntry.objects.filter(register="wd_tr_university").first().organisation
    assert org is not None and org.status == Organisation.Status.CANDIDATE
    assert org.identifiers.filter(scheme="WIKIDATA").exists()
    assert len(org.names) >= 1


def test_a_count_outside_the_bounds_stops_the_row() -> None:
    from apps.research.wikidata import EnumerationShape, fetch_items

    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with pytest.raises(EnumerationShape):
        fetch_items(_row(min_count=100, max_count=400), call=lambda *_a, **_k: body)


def test_a_qid_already_on_another_body_is_a_conflict_not_a_merge() -> None:
    from apps.research.wikidata import Item, record_items

    record_organisation(domain="a.edu.tr", name="A", kind="INSTITUTION", country_code="TR",
                        found_via="x", identifiers=[("WIKIDATA", "Q1")])
    record_organisation(domain="b.edu.tr", name="B", kind="INSTITUTION", country_code="TR",
                        found_via="x")
    report = record_items(
        _row(), (Item("Q1", "B University", ("B University",), ("https://b.edu.tr",)),),
        now=timezone.now(),
    )
    assert report.conflicts == 1
    assert RegisterEntry.objects.get(external_key="Q1").resolution == "CONFLICT"


def test_a_second_qid_on_a_held_website_is_a_conflict_not_a_merge() -> None:
    from apps.research.wikidata import Item, record_items

    record_organisation(domain="c.edu.tr", name="C", kind="INSTITUTION", country_code="TR",
                        found_via="x", identifiers=[("WIKIDATA", "Q7")])
    report = record_items(
        _row(), (Item("Q8", "C Campus", ("C Campus",), ("https://www.c.edu.tr",)),),
        now=timezone.now(),
    )
    assert report.conflicts == 1
    assert RegisterEntry.objects.get(external_key="Q8").resolution == "CONFLICT"


# --- The resolver's half: find_item (rung 1) and sparql (the vocabulary). ---


def _entity(qid, *, country="Q43", site=None, labels=None, aliases=None, dissolved=False):
    claims = {"P17": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": country}}}}]}
    if site:
        claims["P856"] = [{"rank": "normal", "mainsnak": {"datavalue": {"value": site}}}]
    if dissolved:
        claims["P576"] = [
            {"rank": "normal", "mainsnak": {"datavalue": {"value": {"time": "+2001"}}}}
        ]
    return {
        "id": qid,
        "claims": claims,
        "labels": {lang: {"language": lang, "value": v} for lang, v in (labels or {}).items()},
        "aliases": {lang: [{"value": v} for v in vs] for lang, vs in (aliases or {}).items()},
    }


def _api(search_hits, entities):
    calls = []

    def get(url, *, params, headers, **_):
        assert url == wikidata.WIKIDATA_API
        assert headers["User-Agent"]  # Wikimedia's User-Agent policy
        calls.append(params)
        if params["action"] == "wbsearchentities":
            return {"search": [{"id": q} for q in search_hits]}
        return {"entities": {e["id"]: e for e in entities}}

    return get, calls


def test_an_exact_label_in_the_right_country_is_a_match_and_brings_every_variant() -> None:
    get, _ = _api(["Q1"], [_entity(
        "Q1", site="https://www.hrantdink.org/",
        labels={
            "tr": "Hrant Dink Vakfı", "en": "Hrant Dink Foundation", "de": "Hrant-Dink-Stiftung",
        },
        aliases={"ru": ["Фонд Гранта Динка"]},
    )])
    match = wikidata.find_item(
        ["Hrant Dink Vakfı"], country_qid="Q43", languages=("tr", "en", "ru"), get=get
    )
    assert match is not None and match.qid == "Q1"
    assert match.websites == ("https://www.hrantdink.org/",)
    assert match.labels == ("Hrant Dink Vakfı", "Hrant Dink Foundation", "Фонд Гранта Динка")


def test_a_fuzzy_hit_is_never_a_match() -> None:
    # The ROR lesson (4.13a): a plausible top hit is sometimes a different body.
    get, _ = _api(["Q2"], [_entity("Q2", labels={"tr": "İnönü Üniversitesi"})])
    match = wikidata.find_item(["İnönü Vakfı"], country_qid="Q43", languages=("tr",), get=get)
    assert match is None


def test_wrong_country_dissolved_and_ambiguous_items_are_not_matches() -> None:
    other = _entity("Q3", country="Q183", labels={"tr": "TEMA"})
    gone = _entity("Q4", labels={"tr": "TEMA"}, dissolved=True)
    get, _ = _api(["Q3", "Q4"], [other, gone])
    assert wikidata.find_item(["TEMA"], country_qid="Q43", languages=("tr",), get=get) is None
    twins = [_entity("Q5", labels={"tr": "TEMA"}), _entity("Q6", labels={"tr": "TEMA"})]
    get, _ = _api(["Q5", "Q6"], twins)
    assert wikidata.find_item(["TEMA"], country_qid="Q43", languages=("tr",), get=get) is None


def test_a_dissolution_with_an_unknown_date_is_still_a_dissolution() -> None:
    # Wikidata writes "dissolved, date unknown" as a somevalue snak: no datavalue.
    gone = _entity("Q7", labels={"tr": "TEMA Vakfı"})
    gone["claims"]["P576"] = [{"rank": "normal", "mainsnak": {"snaktype": "somevalue"}}]
    get, _ = _api(["Q7"], [gone])
    assert wikidata.find_item(["TEMA Vakfı"], country_qid="Q43", languages=("tr",), get=get) is None


def test_every_hit_is_read_so_a_twin_past_the_first_batch_is_still_ambiguity() -> None:
    hits = [f"Q{n}" for n in range(100, 150)] + ["Q5", "Q6"]
    twins = [_entity("Q5", labels={"tr": "TEMA Vakfı"}), _entity("Q6", labels={"tr": "TEMA Vakfı"})]
    batches = []

    def get(url, *, params, headers, **_):
        if params["action"] == "wbsearchentities":
            return {"search": [{"id": q} for q in hits]}
        batches.append(params["ids"].split("|"))
        return {"entities": {e["id"]: e for e in twins if e["id"] in params["ids"].split("|")}}

    assert wikidata.find_item(["TEMA Vakfı"], country_qid="Q43", languages=("tr",), get=get) is None
    assert [len(b) for b in batches] == [50, 2]


def test_sparql_flattens_bindings_to_values() -> None:
    def get(url, *, params, headers, accept, **_):
        assert url == wikidata.ENDPOINT
        assert headers["User-Agent"]
        assert "application/sparql-results+json" in accept
        return {"results": {"bindings": [{"x": {"type": "literal", "value": "1"}}]}}

    assert wikidata.sparql("SELECT ?x WHERE {}", get=get) == [{"x": "1"}]


# --- The resolver's record (build item 8, Task 6): the enumeration's key. ---


def test_an_enumerated_website_is_a_listed_route() -> None:
    from apps.research.wikidata import Item, record_items

    record_items(_row(), (Item("Q5", "E Uni", ("E Uni",), ("https://e.edu.tr",)),),
                 now=timezone.now())
    entry = RegisterEntry.objects.get(external_key="Q5")
    assert (entry.resolution, entry.resolved_via) == ("RESOLVED", "LISTED")


def test_an_item_that_loses_its_website_goes_unresolved_without_a_route() -> None:
    from apps.research.wikidata import Item, record_items

    record_items(_row(), (Item("Q5", "E Uni", ("E Uni",), ("https://e.edu.tr",)),),
                 now=timezone.now())
    record_items(_row(), (Item("Q5", "E Uni", ("E Uni",), ()),), now=timezone.now())
    entry = RegisterEntry.objects.get(external_key="Q5")
    assert (entry.resolution, entry.resolved_via, entry.organisation) == ("UNRESOLVED", "", None)


def test_a_bound_item_that_becomes_a_conflict_carries_no_route() -> None:
    from apps.research.wikidata import Item, record_items

    record_items(_row(), (Item("Q5", "E Uni", ("E Uni",), ("https://e.edu.tr",)),),
                 now=timezone.now())
    record_organisation(domain="f.edu.tr", name="F", kind="INSTITUTION", country_code="TR",
                        found_via="x", identifiers=[("WIKIDATA", "Q6")])
    record_items(_row(), (Item("Q5", "E Uni", ("E Uni",), ("https://f.edu.tr",)),),
                 now=timezone.now())
    entry = RegisterEntry.objects.get(external_key="Q5")
    assert (entry.resolution, entry.resolved_via, entry.organisation) == ("CONFLICT", "", None)
