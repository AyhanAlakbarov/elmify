from decimal import Decimal
from uuid import uuid4

import pytest

from apps.accounts.consultation import (
    ConsultationDraft,
    _profile_payload,
    consultation_progress,
    next_profile_question,
)
from apps.accounts.field_taxonomy import needs_field_disambiguation, resolve_field_taxonomy
from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.eligibility import ConditionTriple, decide
from apps.funding.facts import score_program_fit
from apps.funding.models import Institution, Program
from apps.funding.pool import candidate_pool
from apps.research.tap_query import inputs_from, render_tap_queries
from apps.research.tap_seams import AngleRow
from tests.accounts.test_profile_schema_v3 import _answers


def _snapshot(**overrides: object) -> StudentProfileSnapshot:
    return StudentProfileSnapshot.model_validate(_answers(**overrides))


def test_ai_with_chemistry_expands_to_digital_chemoinformatics_and_computational_chemistry() -> (
    None
):
    res = resolve_field_taxonomy("AI with chemistry")
    assert res.is_ambiguous_or_interdisciplinary is True
    assert "digital chemistry" in res.canonical_degree_titles
    assert "chemoinformatics" in res.canonical_degree_titles
    assert "cheminformatics" in res.canonical_degree_titles
    assert "computational chemistry" in res.canonical_degree_titles
    assert "chemistry" in res.parent_fields
    assert "digital chemistry" in res.disambiguation_question.lower()
    assert "computational" in res.disambiguation_question.lower()


def test_chemoinformatics_orientation_prefers_chosen_subtrack() -> None:
    ai_oriented = resolve_field_taxonomy(
        "Chemoinformatics", ("AI and machine learning for molecules",)
    )
    quantum_oriented = resolve_field_taxonomy(
        "Chemoinformatics", ("traditional computational and quantum DFT",)
    )
    assert ai_oriented.canonical_degree_titles[0] == "ai and machine learning for molecules"
    assert ai_oriented.canonical_degree_titles.index(
        "digital chemistry"
    ) < ai_oriented.canonical_degree_titles.index("computational chemistry")
    assert quantum_oriented.canonical_degree_titles.index(
        "computational chemistry"
    ) < quantum_oriented.canonical_degree_titles.index("digital chemistry")


def test_compositional_generalization_works_for_any_novel_discipline() -> None:
    res = resolve_field_taxonomy("Machine learning with agriculture")
    assert res.is_ambiguous_or_interdisciplinary is True
    assert "digital agriculture" in res.canonical_degree_titles
    assert "computational agriculture" in res.canonical_degree_titles
    assert "agroinformatics" in res.canonical_degree_titles
    assert "agriculture data science" in res.canonical_degree_titles
    assert res.parent_fields == ("agriculture",)


def test_consultation_dynamically_asks_research_interests_when_field_is_ambiguous() -> None:
    draft = ConsultationDraft(
        tenant_id=uuid4(),
        membership_id=uuid4(),
        answers={
            "nationality": "AZ",
            "country_of_residence": "AZ",
            "date_of_birth": "2002-05-01",
            "target_field": "AI with chemistry",
        },
    )
    nxt = next_profile_question(draft)
    assert nxt is not None
    assert nxt.key == "research_interests"
    assert "AI with chemistry" in nxt.label
    assert "digital chemistry" in nxt.label.lower()

    payload = _profile_payload(draft.with_answer("research_interests", []))
    interests = payload["research_interests"]
    assert isinstance(interests, list)
    assert "digital chemistry" in interests
    assert "chemoinformatics" in interests
    assert "cheminformatics" in interests
    assert "computational chemistry" in interests


def test_unambiguous_single_field_skips_disambiguation_question() -> None:
    assert needs_field_disambiguation("Chemistry") is False
    draft = ConsultationDraft(
        tenant_id=uuid4(),
        membership_id=uuid4(),
        answers={
            "nationality": "AZ",
            "country_of_residence": "AZ",
            "date_of_birth": "2002-05-01",
            "target_field": "Chemistry",
        },
    )
    nxt = next_profile_question(draft)
    assert nxt is not None
    assert nxt.key == "allowed_countries"
    assert consultation_progress(draft)[0] == 4


def test_tap_query_rotates_across_expanded_canonical_degree_titles() -> None:
    profile = _snapshot(
        target_field="AI with chemistry",
        allowed_countries=("FR", "IT"),
    )
    inputs = inputs_from(profile)
    assert "digital chemistry" in inputs.field_words
    assert "chemoinformatics" in inputs.field_words
    assert "cheminformatics" in inputs.field_words
    assert "computational chemistry" in inputs.field_words

    angle = (AngleRow(id="p1", language="en", template="M.Sc. in {field} in {destination}"),)
    rendered = [req.query for _, req in render_tap_queries(inputs, angle)]
    assert any("digital chemistry" in q and "Italy" in q for q in rendered)
    assert any("chemoinformatics" in q and "France" in q for q in rendered)
    assert any("computational chemistry" in q for q in rendered)


@pytest.mark.django_db
def test_pool_and_scoring_find_and_rank_digital_chemistry_and_strasbourg_csc(
    settings,
) -> None:
    settings.PROVENANCE_GATE_ENFORCED = False
    unipd = Institution.objects.create(
        name="University of Padua",
        country_code="IT",
        canonical_key="it:unipd",
        official_website="https://www.unipd.it",
    )
    unistra = Institution.objects.create(
        name="University of Strasbourg",
        country_code="FR",
        canonical_key="fr:unistra",
        official_website="https://www.unistra.fr",
    )
    padua_digital = Program.objects.create(
        institution=unipd,
        name="Master's in Digital Chemistry",
        degree_level="MASTER",
        country_code="IT",
        city="Padua",
        duration_months=24,
        teaching_languages=["English"],
        canonical_key="it:unipd:digital-chemistry",
        location_key="it:padua",
        origin_domain="unipd.it",
    )
    strasbourg_csc = Program.objects.create(
        institution=unistra,
        name="Master in Chemistry — Complex Systems Chemistry (CSC)",
        degree_level="MASTER",
        country_code="FR",
        city="Strasbourg",
        duration_months=24,
        teaching_languages=["English"],
        canonical_key="fr:unistra:csc-chemistry",
        location_key="fr:strasbourg",
        origin_domain="unistra.fr",
    )
    strasbourg_chemo = Program.objects.create(
        institution=unistra,
        name="MSc in Chemoinformatics",
        degree_level="MASTER",
        country_code="FR",
        city="Strasbourg",
        duration_months=24,
        teaching_languages=["English"],
        canonical_key="fr:unistra:chemoinformatics",
        location_key="fr:strasbourg",
        origin_domain="unistra.fr",
    )
    generic_chem = Program.objects.create(
        institution=unipd,
        name="MSc in Organic Synthesis",
        degree_level="MASTER",
        country_code="IT",
        city="Padua",
        duration_months=24,
        teaching_languages=["English"],
        canonical_key="it:unipd:organic",
        location_key="it:padua",
        origin_domain="unipd.it",
    )

    profile = _snapshot(
        target_field="AI with chemistry",
        research_interests=("AI and machine learning for molecules",),
        allowed_countries=("FR", "IT"),
    )
    pool = candidate_pool(profile, limit=10)
    found_keys = {p.canonical_key for p in pool.programs}
    assert "it:unipd:digital-chemistry" in found_keys
    assert "fr:unistra:csc-chemistry" in found_keys
    assert "fr:unistra:chemoinformatics" in found_keys

    scores_digital = score_program_fit(padua_digital, profile)
    scores_chemo = score_program_fit(strasbourg_chemo, profile)
    scores_csc = score_program_fit(strasbourg_csc, profile)
    scores_generic = score_program_fit(generic_chem, profile)

    assert scores_digital["PROGRAM_FIT"] == Decimal("95")
    assert scores_chemo["PROGRAM_FIT"] == Decimal("95")
    assert scores_csc["PROGRAM_FIT"] >= Decimal("90")
    assert scores_digital["PROGRAM_FIT"] > scores_generic["PROGRAM_FIT"]

    # Eligibility FIELD condition for "Chemistry" or "Chemoinformatics" is satisfied
    cond_chem = ConditionTriple(
        key="FIELD",
        operator="IN",
        value="Chemistry, Chemical Sciences",
        quote="Open to Master's students in Chemistry or Chemical Sciences.",
    )
    cond_chemo = ConditionTriple(
        key="FIELD",
        operator="IN",
        value="Chemoinformatics, Digital Chemistry",
        quote="Open to Master's students in Chemoinformatics or Digital Chemistry.",
    )
    assert decide(cond_chem, profile).outcome == "SATISFIED"
    assert decide(cond_chemo, profile).outcome == "SATISFIED"


def test_universal_morphological_juxtaposed_and_isced_generalizability() -> None:
    from apps.accounts.field_taxonomy import (
        enrich_resolution_with_knowledge_graphs,
        localized_field_terms,
    )

    # 1. Single-word morphological compounds across diverse faculties
    for compound_term, expected_parent, expected_title in (
        ("Neuroinformatics", "neuroscience", "digital neuroscience"),
        ("Geoinformatics", "earth sciences", "geoinformatics"),
        ("Pharmacoinformatics", "pharmacology", "pharmacoinformatics"),
        ("Econometrics", "economics", "quantitative economics"),
        ("Agritech", "agriculture", "digital agriculture"),
        ("Legaltech", "law", "legal informatics"),
        ("Biophysics", "biology", "biology and physics"),
        ("Neuroeconomics", "neuroscience", "neuroscience and economics"),
    ):
        res = resolve_field_taxonomy(compound_term)
        assert res.is_ambiguous_or_interdisciplinary is True, compound_term
        assert expected_parent in res.parent_fields, (compound_term, res.parent_fields)
        assert expected_title in res.canonical_degree_titles, (
            compound_term,
            res.canonical_degree_titles,
        )

    # 2. Connector-less juxtaposed interdisciplinary fields
    for phrase, parent_a, parent_b in (
        ("Environmental Economics", "environmental science", "economics"),
        ("Medical Robotics", "medicine", "robotics"),
        ("Financial Mathematics", "finance", "mathematics"),
        ("Law & Technology", "law", "technology"),
    ):
        res = resolve_field_taxonomy(phrase)
        assert res.is_ambiguous_or_interdisciplinary is True, phrase
        assert parent_a in res.parent_fields, (phrase, res.parent_fields)
        assert parent_b in res.parent_fields, (phrase, res.parent_fields)

    # 3. Single foundational ISCED-F disciplines expand synonyms & parents without
    #    blocking the consultation wizard (`is_ambiguous_or_interdisciplinary=False`)
    ir_res = resolve_field_taxonomy("International Relations")
    assert ir_res.is_ambiguous_or_interdisciplinary is False
    assert "international affairs" in ir_res.canonical_degree_titles
    assert "diplomacy" in ir_res.canonical_degree_titles
    assert "political science" in ir_res.parent_fields

    law_res = resolve_field_taxonomy("Law")
    assert law_res.is_ambiguous_or_interdisciplinary is False
    assert "llm" in law_res.canonical_degree_titles
    assert "master of laws" in law_res.canonical_degree_titles

    # 4. Compositional multilingual translation works for unseen combinations
    de_agri = localized_field_terms("digital agriculture", "de")
    assert any("Agrarwissenschaften" in t or "Landwirtschaft" in t for t in de_agri)
    fr_arch = localized_field_terms("computational archaeology", "fr")
    assert any("archéologie" in t for t in fr_arch)
    it_arch = localized_field_terms("sustainable architecture", "it")
    assert any("architettura" in t for t in it_arch)

    # 5. Live knowledge-graph enrichment hook merges OpenAlex & Wikidata aliases
    enriched = enrich_resolution_with_knowledge_graphs(
        law_res,
        openalex_lookup=lambda _q: ("International Dispute Settlement",),
        wikidata_lookup=lambda _q: {"en": ("Jurisprudence",)},
    )
    assert "international dispute settlement" in enriched.canonical_degree_titles
    assert "jurisprudence" in enriched.canonical_degree_titles


class _FakeTaxonomyResponse:
    def __init__(self, output_parsed: object) -> None:
        self.output_parsed = output_parsed


class _FakeTaxonomyParser:
    def __init__(self, output_parsed: object) -> None:
        self._output = output_parsed
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self._output, Exception):
            raise self._output
        return _FakeTaxonomyResponse(self._output)


def test_llm_taxonomy_enriches_free_text_description_and_propagates_to_callers() -> None:
    from pydantic import ValidationError

    from apps.accounts.field_taxonomy import (
        LLMFieldExpansion,
        LLMFieldOrientation,
        LLMLocalizedFieldTerms,
        clear_field_taxonomy_cache,
        localized_field_terms,
        localized_field_terms_with_llm,
        resolve_field_taxonomy_with_llm,
    )
    from apps.research.tap_query import inputs_from

    clear_field_taxonomy_cache()
    try:
        # Closed schema rejects unknown fields
        with pytest.raises(ValidationError):
            LLMFieldExpansion.model_validate(
                {
                    "is_interdisciplinary_or_broad": True,
                    "canonical_degree_titles": ["precision agriculture"],
                    "parent_fields": ["agriculture"],
                    "orientations": [],
                    "unexpected": "field",
                }
            )

        expansion = LLMFieldExpansion(
            is_interdisciplinary_or_broad=True,
            canonical_degree_titles=[
                "precision agriculture at Harvard University 2026",
                "earth observation and geoinformatics site:evil.com",
                "remote sensing for Khazar agriculture",
            ],
            parent_fields=["agriculture", "geography"],
            orientations=[
                LLMFieldOrientation(
                    slug="satellite_remote_sensing",
                    label="satellite remote sensing and earth observation",
                    trigger_keywords=["satellite", "remote sensing", "drought"],
                    degree_titles=["earth observation and geoinformatics", "remote sensing"],
                    track_keywords=["remote sensing", "geoinformatics", "satellite"],
                ),
                LLMFieldOrientation(
                    slug="agronomy_crop_modeling",
                    label="crop modeling and climate-resilient agronomy",
                    trigger_keywords=["crop", "farmers", "agronomy"],
                    degree_titles=["precision agriculture", "sustainable agriculture"],
                    track_keywords=["agronomy", "precision agriculture"],
                ),
            ],
        )
        parser = _FakeTaxonomyParser(expansion)
        raw_input = "helping farmers adapt to drought with satellite data"

        res = resolve_field_taxonomy_with_llm(
            raw_input,
            parser=parser,
            student_id="student-42",
            banned=frozenset({"khazar"}),
        )
        assert len(parser.calls) == 1
        call = parser.calls[0]
        assert call["store"] is False
        assert int(call["max_output_tokens"]) <= 600
        assert call["safety_identifier"] != "student-42"
        assert "DATA:" in str(call["input"])

        # PII / institution / year / operator / banned school scrubbed
        joined_titles = " ".join(res.canonical_degree_titles)
        for forbidden in ("harvard", "2026", "site:", "evil.com", "khazar"):
            assert forbidden not in joined_titles

        assert res.is_ambiguous_or_interdisciplinary is True
        assert "precision agriculture" in res.canonical_degree_titles
        assert "earth observation and geoinformatics" in res.canonical_degree_titles
        assert "agriculture" in res.parent_fields
        assert "geography" in res.parent_fields
        assert "With" in res.disambiguation_question

        # Cache-through: calling `resolve_field_taxonomy` (and `inputs_from`) now
        # returns the enriched resolution without another LLM call.
        cached_res = resolve_field_taxonomy(raw_input)
        assert cached_res == res
        assert len(parser.calls) == 1

        profile = _snapshot(target_field=raw_input, research_interests=[])
        tap_inputs = inputs_from(profile)
        assert "precision agriculture" in tap_inputs.field_words
        assert "earth observation and geoinformatics" in tap_inputs.field_words

        # Localized LLM terms also cache through to `localized_field_terms`
        loc_parser = _FakeTaxonomyParser(
            LLMLocalizedFieldTerms(
                terms=["Präzisionslandwirtschaft", "Fernerkundung und Geoinformatik 2026"]
            )
        )
        de_terms = localized_field_terms_with_llm(
            raw_input, "de", parser=loc_parser, student_id="student-42"
        )
        assert "präzisionslandwirtschaft" in de_terms
        assert "fernerkundung und geoinformatik" in de_terms
        assert localized_field_terms(raw_input, "de") == de_terms
    finally:
        clear_field_taxonomy_cache()


def test_llm_taxonomy_logs_and_falls_back_cleanly_on_rate_limit_or_failure(
    monkeypatch, caplog
) -> None:
    from apps.accounts.field_taxonomy import (
        clear_field_taxonomy_cache,
        resolve_field_taxonomy_with_llm,
    )

    clear_field_taxonomy_cache()
    try:
        # 1. Refusal / None output logs warning and does not cache failure
        refusal_parser = _FakeTaxonomyParser(None)
        res = resolve_field_taxonomy_with_llm(
            "AI with chemistry", parser=refusal_parser, student_id="stu-1"
        )
        assert "chemoinformatics" in res.canonical_degree_titles
        assert any("no parsed payload" in rec.message for rec in caplog.records)

        # 2. Rate limit logs warning and skips model call
        caplog.clear()
        monkeypatch.setattr("apps.accounts.field_taxonomy.rate_limited", lambda *a, **k: True)
        rl_parser = _FakeTaxonomyParser(None)
        res_rl = resolve_field_taxonomy_with_llm(
            "AI with chemistry", parser=rl_parser, student_id="stu-1"
        )
        assert "chemoinformatics" in res_rl.canonical_degree_titles
        assert rl_parser.calls == []
        assert any("rate-limited" in rec.message for rec in caplog.records)
    finally:
        clear_field_taxonomy_cache()


def test_universal_122_majors_and_edge_case_bug_fixes() -> None:
    from apps.accounts.field_taxonomy import _DISCIPLINE_NODES, localized_field_terms

    # 1. At least 120 canonical university majors across all ISCED-F / CIP / HECoS categories
    assert len(_DISCIPLINE_NODES) >= 120

    # 2. Hyphenated single disciplines do not split into false dual-domain hybrids
    hci = resolve_field_taxonomy("Human-Computer Interaction")
    assert hci.is_ambiguous_or_interdisciplinary is False
    assert "human-computer interaction" in hci.canonical_degree_titles
    assert "user experience design" in hci.canonical_degree_titles
    assert "computer science" in hci.parent_fields

    # 3. Hyphenated morphological compounds decompose cleanly
    neuro_hyph = resolve_field_taxonomy("neuro-informatics")
    assert neuro_hyph.is_ambiguous_or_interdisciplinary is True
    assert "neuroscience" in neuro_hyph.parent_fields
    assert "digital neuroscience" in neuro_hyph.canonical_degree_titles

    # 4. Multi-word domain phrases containing "science" preserve "science" when
    #    stripped of single-word method prefixes
    comp_soc = resolve_field_taxonomy("computational social science")
    assert comp_soc.is_ambiguous_or_interdisciplinary is True
    assert "computational sociology" in comp_soc.canonical_degree_titles
    assert "social informatics" in comp_soc.canonical_degree_titles
    assert "sociology" in comp_soc.parent_fields

    ai_food = resolve_field_taxonomy("AI in food science")
    assert ai_food.is_ambiguous_or_interdisciplinary is True
    assert "food science" in ai_food.parent_fields

    # 5. "Sustainable organic agriculture" does not false-match chemistry_computation_ai
    sust_org_ag = resolve_field_taxonomy("sustainable organic agriculture")
    assert "chemoinformatics" not in sust_org_ag.canonical_degree_titles
    assert "agriculture" in sust_org_ag.parent_fields

    # 6. Word-bounded orientation triggers: "paint" or "daily" does not trigger "ai"
    non_ai = resolve_field_taxonomy("Chemoinformatics", ("daily synthesis of paint pigments",))
    # Without an actual "ai" / "ml" / "quantum" word boundary match, default ordering applies
    assert non_ai.canonical_degree_titles[1] == "digital chemistry"

    # 7. Representative newly added majors resolve with full multilingual translations
    for major, expected_parent, lang, expected_loc in (
        ("Optometry", "medicine", "de", "augenoptik"),
        ("Actuarial Science", "mathematics", "fr", "actuariat"),
        ("Naval Architecture", "mechanical engineering", "tr", "gemi"),
        ("Criminology", "sociology", "it", "criminologia"),
        ("Enology and Viticulture", "food science", "fr", "œnologie"),
        ("Translation and Interpreting", "linguistics", "de", "dolmetschen"),
        ("Supply Chain Management", "business administration", "nl", "supply chain"),
        ("Speech-Language Pathology", "health sciences", "fr", "orthophonie"),
    ):
        res = resolve_field_taxonomy(major)
        assert res.is_ambiguous_or_interdisciplinary is False, major
        assert expected_parent in res.parent_fields, (major, res.parent_fields)
        loc = localized_field_terms(major, lang)
        assert any(expected_loc in t.casefold() for t in loc), (major, lang, loc)


def test_native_language_input_resolution_and_free_text_sentence_guard() -> None:
    from apps.accounts.field_taxonomy import (
        localized_field_terms,
        needs_llm_taxonomy_enrichment,
    )

    # 1. Native-language inputs resolve deterministically in 0ms via _DISCIPLINE_BY_SYNONYM
    for native_input, expected_canonical, expected_parent in (
        ("chimica", "chemistry", "natural sciences"),
        ("informatique", "computer science", "computer science"),
        ("kompüter elmləri", "computer science", "computer science"),
        ("Maschinenbau", "mechanical engineering", "engineering"),
        ("计算机科学", "computer science", "computer science"),
    ):
        res = resolve_field_taxonomy(native_input)
        assert expected_canonical in res.canonical_degree_titles, (native_input, res)
        assert expected_parent in res.parent_fields, (native_input, res)
        assert needs_llm_taxonomy_enrichment(res) is False

    # Cross-language translation from a native input ("chimica" -> German "Chemie")
    de_from_it = localized_field_terms("chimica", "de")
    assert any("chemie" in t.casefold() for t in de_from_it)

    # 2. Free-text sentence with "with" / "to" does not falsely split into fake domains
    free_text = "helping farmers adapt to drought with satellite data"
    ft_res = resolve_field_taxonomy(free_text)
    assert "helping farmers adapt" not in ft_res.parent_fields
    assert needs_llm_taxonomy_enrichment(ft_res) is True

    # 3. Cross-process Stage 6 reconstruction from research_interests recovers parent_fields
    reconstructed = resolve_field_taxonomy(
        free_text,
        ("precision agriculture", "earth observation and geoinformatics"),
    )
    assert "agriculture" in reconstructed.parent_fields
    assert "earth sciences" in reconstructed.parent_fields
    assert needs_llm_taxonomy_enrichment(reconstructed) is False


def test_openrouter_chinese_model_parser_and_multilingual_arabic_regional_phrases(settings) -> None:
    import json
    from types import SimpleNamespace

    from apps.accounts.field_taxonomy import (
        DEFAULT_CHINESE_FLASH_MODEL,
        DEFAULT_CHINESE_FRONTIER_MODEL,
        LLMLocalizedFieldTerms,
        OpenRouterTaxonomyParser,
        clear_field_taxonomy_cache,
        localized_field_terms,
        localized_field_terms_with_llm,
        openrouter_taxonomy_parser,
    )

    clear_field_taxonomy_cache()
    try:
        # 1. Deterministic Arabic (`ar`) and Southeast Asian / European terms
        ar_cs = localized_field_terms("computer science", "ar")
        assert "علوم الحاسب" in ar_cs
        ar_digital_chem = localized_field_terms("digital chemistry", "ar")
        assert "الكيمياء الرقمية" in ar_digital_chem
        id_ai = localized_field_terms("artificial intelligence", "id")
        assert "kecerdasan buatan" in id_ai
        hu_cs = localized_field_terms("computer science", "hu")
        assert "számítástudomány" in hu_cs

        # 2. `OpenRouterTaxonomyParser` sends strict json_schema with reasoning disabled to
        # `deepseek/deepseek-v4.1-flash` (or `moonshotai/kimi-k3`)
        captured: list[dict[str, object]] = []

        def _fake_completion(**kwargs: object) -> object:
            captured.append(kwargs)
            payload = json.dumps({"terms": ["الزراعة الدقيقة", "الاستشعار عن بعد"]})
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
            )

        parser = OpenRouterTaxonomyParser(
            api_key="sk-or-test",
            default_model=DEFAULT_CHINESE_FLASH_MODEL,
            host="inference-net/fp8",
            post_completion=_fake_completion,
        )
        terms = localized_field_terms_with_llm(
            "precision agriculture",
            "ar",
            parser=parser,
            student_id="stu-ar-1",
        )
        assert "الزراعة الدقيقة" in terms
        assert len(captured) == 1
        req = captured[0]
        assert req["model"] == DEFAULT_CHINESE_FLASH_MODEL
        assert req["temperature"] == 0
        assert req["extra_body"] == {
            "reasoning": {"enabled": False},
            "provider": {
                "order": ["inference-net/fp8"],
                "allow_fallbacks": False,
                "require_parameters": True,
            },
        }
        assert req["response_format"]["json_schema"]["strict"] is True  # type: ignore[index]
        assert req["response_format"]["json_schema"]["name"] == LLMLocalizedFieldTerms.__name__  # type: ignore[index]

        # 3. `openrouter_taxonomy_parser` factory respects `OPENROUTER_API_KEY` and model choice
        settings.OPENROUTER_API_KEY = ""
        assert openrouter_taxonomy_parser() is None
        settings.OPENROUTER_API_KEY = "sk-or-live"
        kimi_parser = openrouter_taxonomy_parser(
            model=DEFAULT_CHINESE_FRONTIER_MODEL, host="makora"
        )
        assert kimi_parser is not None
        assert kimi_parser.default_model == DEFAULT_CHINESE_FRONTIER_MODEL
        assert kimi_parser.host == "makora"
    finally:
        clear_field_taxonomy_cache()


def test_clear_field_taxonomy_cache_clears_keys_from_other_workers() -> None:
    """When a key is set in shared cache by another worker (not in local _SHARED_CACHE_KEYS),
    clear_field_taxonomy_cache must still evict it from shared cache."""
    from django.core.cache import cache

    from apps.accounts.field_taxonomy import (
        _SHARED_CACHE_KEYS,
        _shared_cache_get,
        _shared_cache_key,
        _shared_cache_set,
        clear_field_taxonomy_cache,
    )

    clear_field_taxonomy_cache()

    # Simulate Worker 1 setting a key
    key = _shared_cache_key("res", ("Test Field", ()))
    _shared_cache_set(key, {"mock": "data"})
    assert _shared_cache_get(key) == {"mock": "data"}

    # Simulate Worker 2 by clearing the process-local set (as in a separate worker process)
    _SHARED_CACHE_KEYS.clear()

    # Worker 2 calls clear_field_taxonomy_cache()
    clear_field_taxonomy_cache()

    # The key set by Worker 1 MUST be evicted from shared cache
    assert _shared_cache_get(key) is None
    assert cache.get(key) is None

