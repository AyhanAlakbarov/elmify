"""The resolver's reading of a name (spec 6.5, rules 1 and 3; 4.13b's symmetric fold)."""

from apps.research.names import fold, kind_of, profile, tokens
from apps.research.vocabulary import Vocabulary

FOUNDATION, ASSOCIATION, UNIVERSITY, EMBASSY = "Q157031", "Q48204", "Q3918", "Q3917681"


def vocab(**overrides) -> Vocabulary:
    fields = dict(
        country_code="TR", country_qid="Q43", cctld="tr", languages=("tr", "en", "ru"),
        kinds={
            "stiftung": frozenset({FOUNDATION}), "vakif": frozenset({FOUNDATION}),
            "foundation": frozenset({FOUNDATION}), "dernegi": frozenset({ASSOCIATION}),
            "association": frozenset({ASSOCIATION}), "university": frozenset({UNIVERSITY}),
            "embassy": frozenset({EMBASSY}),
        },
        geo=frozenset({"turkiye", "turkey", "turk", "stuttgart", "istanbul"}),
        generic=frozenset({"egitim", "kultur"}),
    )
    fields.update(overrides)
    return Vocabulary(**fields)


def test_folding_is_symmetric_across_scripts_and_umlaut_spellings() -> None:
    # A name and a domain label meet only after the SAME fold: "Hör" and "hoer"
    # must both become "hor", or kind-hoerstiftung.de never matches its name.
    assert fold("Kind Hörstiftung") == fold("kind hoerstiftung") == "kind horstiftung"
    assert fold("İnönü Vakfı") == "inonu vakfi"
    assert tokens("Georgian Young Lawyers' Association") == (
        "georgian", "young", "lawyers", "association",
    )
    assert tokens("საქართველო")  # romanised to something, never empty


def test_kind_words_tolerate_morphology_and_compounds() -> None:
    v = vocab()
    assert kind_of("vakfi", v) == {FOUNDATION}          # vakfı ~ vakıf, one transposition
    assert kind_of("vakiflar", v) == {FOUNDATION}       # inflection
    assert kind_of("stiftungen", v) == {FOUNDATION}
    assert kind_of("bundesstiftung", v) == {FOUNDATION}  # rule 3: ends with a kind word
    assert kind_of("embassies", v) == {EMBASSY}
    assert kind_of("universitesi", v) == {UNIVERSITY}
    assert kind_of("hirschfeld", v) == frozenset()
    assert kind_of("federal", v) == frozenset()


def test_a_profile_separates_distinctive_tokens_from_kind_place_and_common_words() -> None:
    p = profile(["İstanbul Eğitim ve Kültür Vakfı"], vocab())
    assert p.distinctive == frozenset()                 # every word is place, common or kind
    assert p.kinds == {FOUNDATION}
    assert "istek" not in p.initials                     # syllabic: no lexical rule reaches it
    assert "iekv" in p.initials and "ievkv" in p.initials


def test_every_name_variant_is_scored_as_one_union() -> None:
    # Rule 4: Georgian domains are acronyms of the ENGLISH name.
    native = profile(["საქართველოს ახალგაზრდა იურისტთა ასოციაცია"], vocab())
    both = profile(
        ["საქართველოს ახალგაზრდა იურისტთა ასოციაცია", "Georgian Young Lawyers' Association"],
        vocab(),
    )
    assert "gyla" not in native.initials
    assert "gyla" in both.initials


def test_a_name_with_one_token_and_no_kind_word_cannot_be_resolved_from_search() -> None:
    assert profile(["TEMA"], vocab()).one_token
    assert profile(["Cusanuswerk"], vocab()).one_token
    assert not profile(["TEMA Vakfı"], vocab()).one_token
    assert not profile(["Hrant Dink Vakfı"], vocab()).one_token
