"""v4's lexical tiers plus rules 1-3, pinned by the cases that were measured wrong."""

from apps.research.names import profile
from apps.research.resolver import ranked, score_candidate
from tests.research.test_names import vocab


def _best(name_or_names, urls, **overrides):
    names = [name_or_names] if isinstance(name_or_names, str) else name_or_names
    v = vocab(**overrides)
    scored = [s for s in ranked([urls], profile(names, v), v) if s.score > 0]
    return scored[0].domain if scored else ""


def test_the_best_score_wins_not_the_first_match() -> None:
    # 4.13a: zeiss.com matched one token when a better candidate matched more.
    assert _best("Carl-Zeiss-Stiftung",
                 ["https://www.zeiss.com/", "https://www.schott.com/",
                  "https://www.carl-zeiss-stiftung.de/"],
                 cctld="de") == "carl-zeiss-stiftung.de"


def test_a_kind_word_inside_a_compound_is_not_a_distinctive_match() -> None:
    # 4.13a: bund.de matched a 4-letter token inside "Bundesstiftung".
    assert _best("Bundesstiftung Magnus Hirschfeld",
                 ["https://www.bund.de/", "https://mh-stiftung.de/"], cctld="de") != "bund.de"


def test_a_place_never_forms_a_tier_two_label() -> None:
    # v2 finding 1: caritas + stuttgart was promoted as token + "one generic word".
    v = vocab(cctld="de")
    p = profile(["Caritas Stiftung Stuttgart"], v)
    s = score_candidate("https://caritasstuttgart.de/", 0, p, v)
    assert s is not None and s.tier == 1


def test_the_org_word_and_the_cctld_break_ties() -> None:
    # 4.13a: tema.org (a US association) over tema.org.tr on rank alone.
    assert _best("TEMA Vakfı",
                 ["https://www.tema.org/", "https://www.tema.org.tr/"]) == "tema.org.tr"


def test_an_inflected_token_still_reaches_its_domain() -> None:
    # v4's one rescue: kanservakfi.com for Kanserle Savaş Vakfı (kanser+le).
    assert _best("Kanserle Savaş Vakfı",
                 ["https://kansersavascilari.org/",
                  "https://www.kanservakfi.com/"]) == "kanservakfi.com"


def test_a_label_made_only_of_kind_and_place_words_is_a_directory() -> None:
    # Rule 1: embassies.info, stiftungen.de, vakiflar.gov.tr -- a structural denylist.
    v = vocab()
    p = profile(["Embassy of Italy in Astana"], v)
    for url in ("https://embassies.info/italy", "https://www.stiftungen.de/"):
        s = score_candidate(url, 0, p, v)
        assert s is not None and s.directory and s.score == 0


def test_initials_and_full_slug_are_tier_three() -> None:
    v = vocab()
    tskgv = profile(["Türk Silahlı Kuvvetlerini Güçlendirme Vakfı"], v)
    assert score_candidate("https://www.tskgv.org.tr/", 5, tskgv, v).tier == 3
    gyla = profile(["Georgian Young Lawyers' Association"], v)
    assert score_candidate("https://gyla.ge/", 2, gyla, v).tier == 3


def test_an_unkeyable_host_is_never_a_candidate() -> None:
    """Aggregators are refused one step earlier, in the lookup itself --
    tests/research/providers/test_tavily.py pins that."""
    v = vocab()
    p = profile(["Hrant Dink Vakfı"], v)
    assert score_candidate("https://192.0.2.1/", 0, p, v) is None


def test_the_union_of_variant_lists_keeps_each_domain_s_best_rank() -> None:
    v = vocab()
    p = profile(["Hrant Dink Vakfı", "Hrant Dink Foundation"], v)
    order = ranked([["https://a.example.org/", "https://hrantdink.org/"],
                    ["https://hrantdink.org/en"]], p, v)
    assert [s for s in order if s.domain == "hrantdink.org"][0].rank == 0


def test_a_brand_compounded_with_a_kind_word_is_not_a_directory() -> None:
    # Review of Task 3: rule 3's compound match read "boschstiftung" as a kind
    # word, so the true site scored zero as a directory.
    v = vocab(cctld="de")
    p = profile(["Robert Bosch Stiftung"], v)
    s = score_candidate("https://www.bosch-stiftung.de/", 0, p, v)
    assert s is not None and not s.directory and s.tier == 2
    assert _best("Robert Bosch Stiftung",
                 ["https://www.bosch.com/", "https://www.bosch-stiftung.de/"],
                 cctld="de") == "bosch-stiftung.de"
    # An inflected kind word alone is still a directory.
    assert score_candidate("https://www.stiftungen.de/", 0, p, v).directory
