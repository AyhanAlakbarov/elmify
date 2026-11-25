"""Unit tests for Work Package 4 (Stage 6 & Stage 7 fixes and scilit humanize port)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.documents import dates, id_reading, mrz, text_reading, transcript
from apps.documents.credits import _is_master_qualification, infer_local_credits_per_year
from apps.documents.degree_match import degree_level
from apps.documents.europass import EuropassUnavailable, _language_code
from apps.documents.evidence.publication import author_in_byline
from apps.documents.evidence.signals import (
    file_signals,
    interesting_paths,
    manifest_libraries,
)
from apps.documents.letter_gates import (
    GateCode,
    check_ai_style,
    check_claim_coverage,
    run_letter_gates,
)
from apps.documents.letter_schemas import (
    ClaimKind,
    LetterClaim,
    LetterContent,
    LetterUnit,
)
from apps.documents.letter_verification import sourced_claim_matches
from apps.documents.letters import _DOC_LANG_ALIASES, _student_cefr_for_language
from apps.documents.models import Referee, VerifiedFact
from apps.documents.ocr import OcrPage
from apps.documents.referee_evidence import (
    classify_referee_role,
    referee_angle,
)
from apps.documents.referee_package import (
    _DOUBT_CONCESSION_RE,
    _DOUBT_PREPARED_RE,
    _DOUBT_RAISERS_RE,
    _repair_referee_language,
    _sanitize_referee_prose,
    is_webmail_address,
    mask_pii_for_referee_llm,
)
from apps.documents.research_fit.anchors import guard_phrase, strip_named_runs
from apps.documents.research_fit.classify import _INACTIVE_PERSON_RE
from apps.documents.research_fit.papers import person_matches_author
from apps.documents.research_fit.split import page_sentences
from apps.documents.storyline import choose_opening_kind
from apps.documents.table import _CERTIFIED, kinds_named
from apps.documents.transcript_pages import _LANGUAGES, is_english


def test_group1_regional_webmail_domains_flagged() -> None:
    for domain in (
        "qq.com",
        "163.com",
        "126.com",
        "naver.com",
        "daum.net",
        "kakao.com",
        "hanmail.net",
        "yahoo.co.jp",
        "yahoo.co.uk",
        "yahoo.fr",
        "yahoo.de",
        "mail.ru",
        "bk.ru",
        "inbox.ru",
        "list.ru",
        "rambler.ru",
        "ukr.net",
        "wp.pl",
        "onet.pl",
        "interia.pl",
        "o2.pl",
        "seznam.cz",
        "centrum.cz",
        "freemail.hu",
        "abv.bg",
        "azet.sk",
        "mynet.com",
        "box.az",
        "day.az",
        "rediffmail.com",
        "t-online.de",
        "freenet.de",
        "orange.fr",
        "laposte.net",
        "sfr.fr",
        "free.fr",
        "libero.it",
        "virgilio.it",
        "alice.it",
        "terra.com.br",
        "uol.com.br",
        "bol.com.br",
    ):
        assert is_webmail_address(f"prof@{domain}"), domain
    assert not is_webmail_address("prof@tsinghua.edu.cn")
    assert not is_webmail_address("prof@snu.ac.kr")


def test_group1_mask_pii_unicode_and_common_english_name_tokens() -> None:
    student = SimpleNamespace(
        display_name="Will Grant",
        application_email="will.grant@example.com",
        user=SimpleNamespace(
            email="will.grant@example.com",
            first_name="Will",
            last_name="Grant",
        ),
    )
    ref = Referee(title="Prof.", name="May Mark", email="may.mark@tum.de")
    text = "Will Grant will grant the request in May and mark the plan with grace."
    masked, _mapping = mask_pii_for_referee_llm(
        text, student=student, referee=ref  # type: ignore[arg-type]
    )
    assert "will grant the request" in masked
    assert "and mark the plan with grace." in masked
    assert "[CANDIDATE_NAME]" in masked

    cjk_student = SimpleNamespace(
        display_name="张伟",
        application_email="",
        user=SimpleNamespace(email="", first_name="伟", last_name="张"),
    )
    cjk_text = "我指导了张伟的毕业论文，张伟表现出色。"
    cjk_masked, _ = mask_pii_for_referee_llm(
        cjk_text, student=cjk_student, referee=ref  # type: ignore[arg-type]
    )
    assert "张伟" not in cjk_masked
    assert cjk_masked.count("[CANDIDATE_NAME]") == 2


def test_group1_doubt_raisers_contextual_patterns_avoid_false_positives() -> None:
    good = (
        "She is well prepared to tackle the mathematical rigor of the M.Sc. "
        "Even though the timeline was compressed, she delivered the full proof."
    )
    assert not _DOUBT_RAISERS_RE.search(good)
    assert not _DOUBT_PREPARED_RE.search(good)
    assert not _DOUBT_CONCESSION_RE.search(good)

    assert _DOUBT_PREPARED_RE.search("He is adequately prepared for the seminar.")
    assert _DOUBT_CONCESSION_RE.search("Despite initial struggles, she completed the module.")
    assert _DOUBT_RAISERS_RE.search("He appears to be ready for graduate study.")


def test_group1_repair_referee_language_scilit_humanize_port() -> None:
    raw = (
        "wholeheartedly recommend this student. "
        "She is a eagle in the the lab , and an university scholar.. "
        "despite initial struggles, she built a pipeline."
    )
    repaired = _sanitize_referee_prose(raw)
    assert "wholeheartedly" not in repaired
    assert "an eagle" in repaired
    assert "a university" in repaired
    assert "the the" not in repaired
    assert "She built a pipeline." in repaired
    assert _repair_referee_language("a honest assessment.") == "An honest assessment."


def test_group1_multilingual_referee_roles_and_angles() -> None:
    ref_research = Referee(kind=Referee.Kind.ACADEMIC, relationship="Tez danışmanım")
    assert classify_referee_role(ref_research, ()) == "research_supervisor"

    ref_course = Referee(kind=Referee.Kind.ACADEMIC, relationship="Преподаватель курса")
    assert classify_referee_role(ref_course, ()) == "course_instructor"

    ref_prof = Referee(kind=Referee.Kind.ACADEMIC, relationship="Maître de stage")
    assert classify_referee_role(ref_prof, ()) == "professional_supervisor"

    ref_de = Referee(kind=Referee.Kind.ACADEMIC, relationship="Betreuer meiner Bachelorarbeit")
    assert "research" in referee_angle(ref_de, ()).lower()

    ref_fr = Referee(kind=Referee.Kind.ACADEMIC, relationship="Enseignant du cours Algorithmes")
    assert "classroom" in referee_angle(ref_fr, ()).lower()


def test_group2_german_noun_capitalization_vs_entity_detection_in_letter_gates() -> None:
    de_unit = LetterUnit(
        archetype="ACADEMIC_PREPARATION",
        text="Im Studium der Informatik habe ich Algorithmen und Datenbanken vertieft.",
        claims=(),
    )
    assert check_claim_coverage(de_unit, document_language="de") == ()

    de_entity_content = LetterContent(
        language="de",
        units=(
            LetterUnit(
                archetype="WHY_PROGRAMME",
                text="Ich möchte am Lehrstuhl für Robotik mit Prof. Dr. Müller arbeiten.",
                claims=(),
            ),
        ),
    )
    violations = run_letter_gates(
        de_entity_content,
        forbidden_names=frozenset(),
        questions=[],
        header_block_required=False,
        document_language="de",
        paired_content=None,
        storyline=None,
    )
    assert any(v.code == GateCode.UNDECLARED_ASSERTION for v in violations)


def test_group2_cjk_and_non_english_ai_style_gate() -> None:
    cjk_text = (
        "在本科阶段的研究中，我独立完成了分布式图计算引擎的设计与实现，将查询延迟降低了百分之四十。"
        "此外，我还参与了实验室的编译器优化项目。"
        "这段经历让我明确了在研究生阶段继续深耕系统方向的目标，并希望加入贵校的系统实验室开展深入研究。"
    )
    claim = LetterClaim(
        text="分布式图计算引擎",
        span_start=0,
        span_end=len(cjk_text),
        kind=ClaimKind.FACTUAL,
        fact_id=uuid4(),
    )
    content = LetterContent(
        language="zh",
        units=(LetterUnit(archetype="ACADEMIC_PREPARATION", text=cjk_text, claims=(claim,)),),
    )
    assert check_ai_style(content) == ()


def test_group2_sourced_claim_matches_formatted_thousands_and_world_bank_aliases() -> None:
    claim_comma = LetterClaim(
        text="The Robotics Lab award provides 40,000 EUR per year.",
        span_start=0,
        span_end=52,
        kind=ClaimKind.SOURCED,
        source_url="https://tum.de/funding",
    )
    prov_num = {
        "entity": "Robotics Lab",
        "sentence": "The Robotics Lab award provides 40000 EUR per year.",
        "source_url": "https://tum.de/funding",
    }
    assert sourced_claim_matches(claim_comma, prov_num)

    claim_dot = LetterClaim(
        text="Das Robotics Lab Stipendium beträgt 40.000 Euro.",
        span_start=0,
        span_end=48,
        kind=ClaimKind.SOURCED,
        source_url="https://tum.de/funding",
    )
    assert sourced_claim_matches(claim_dot, prov_num)

    claim_wb = LetterClaim(
        text="Das Land steht auf der Liste der Weltbank.",
        span_start=0,
        span_end=42,
        kind=ClaimKind.SOURCED,
        source_url="https://worldbank.org/list",
    )
    prov_wb = {
        "entity": "World Bank",
        "sentence": "World Bank Developing Countries List",
        "source_url": "https://worldbank.org/list",
    }
    assert sourced_claim_matches(claim_wb, prov_wb)


def test_group2_letters_language_aliases_and_exam_language_inference() -> None:
    assert "spanish" in _DOC_LANG_ALIASES["es"]
    assert "portuguese" in _DOC_LANG_ALIASES["pt"]
    assert "polish" in _DOC_LANG_ALIASES["pl"]
    assert "arabic" in _DOC_LANG_ALIASES["ar"]
    assert "ukrainian" in _DOC_LANG_ALIASES["uk"]
    assert "azerbaijani" in _DOC_LANG_ALIASES["az"]

    fact_es = VerifiedFact(
        category=VerifiedFact.Category.LANGUAGE,
        payload={"language": "Spanish", "cefr_level": "B2"},
    )
    assert _student_cefr_for_language({uuid4(): fact_es}, "es") == "B2"

    fact = VerifiedFact(
        category=VerifiedFact.Category.LANGUAGE,
        payload={"test_name": "TestDaF", "cefr_level": "C1"},
    )
    assert _student_cefr_for_language({uuid4(): fact}, "de") == "C1"


def test_group2_storyline_uk_pool_for_system_b_countries() -> None:
    for cc in ("UK", "GB", "AU", "NZ", "IE"):
        kind = choose_opening_kind(
            country_code=cc,
            document_language="en",
            seed_key="",
        )
        assert kind == "real_moment_scene"


def test_group3_transcript_minimised_preserves_postal_headers_and_course_codes() -> None:
    page = OcrPage(
        lines=(
            "119991, МГУ имени М.В. Ломоносова",
            "北京大学 100871",
            "Nom et prénom : Jean Dupont",
            "Matrikelnummer: 1234567",
        ),
        tables=(
            (
                ("101001", "Algorithms", "6", "A"),
                ("101002", "Operating Systems", "6", "A"),
                ("101003", "Compilers", "6", "B"),
            ),
        ),
    )
    lines, tables, _conf, _origins = transcript._minimised((page,), names=frozenset())
    joined_lines = "\n".join(lines)
    joined_tables = "\n".join(
        " ".join(row) for table in tables for row in table
    )
    assert "МГУ имени М.В. Ломоносова" in joined_lines
    assert "119991" not in joined_lines
    assert "北京大学" in joined_lines
    assert "100871" not in joined_lines
    assert "Jean Dupont" not in joined_lines
    assert "1234567" not in joined_lines
    assert "101001" in joined_tables and "101002" in joined_tables and "101003" in joined_tables


def test_group3_transcript_line_fullwidth_colon_and_colon_degree_guard() -> None:
    assert transcript._NON_LABEL_COLON_PREFIX.search("Bachelor of Science")
    assert transcript._NON_LABEL_COLON_PREFIX.search("Master of Arts")
    assert not transcript._NON_LABEL_COLON_PREFIX.search("Qualification")
    assert not transcript._NON_LABEL_COLON_PREFIX.search("专业")


def test_group3_transcript_pages_languages_and_is_english() -> None:
    for code in ("de", "fr", "es", "it", "pt", "nl", "pl", "zh", "ja", "ko", "ar", "uk", "ka"):
        assert code in _LANGUAGES
    assert "en" not in _LANGUAGES
    assert "zz" not in _LANGUAGES

    zh_page = OcrPage(
        lines=("北京大学成绩单", "课程名称 学分 成绩", "高等数学 5 95"),
        tables=(),
    )
    assert not is_english(zh_page)

    fr_page = OcrPage(
        lines=("Relevé de notes", "Matière Crédits Moyenne Session Admis"),
        tables=(),
    )
    assert not is_english(fr_page)


def test_group3_degree_level_and_spain_ects() -> None:
    for deg in (
        "LL.M. in International Law",
        "Master of Business Administration (MBA)",
        "M.Tech in Computer Science",
        "Laurea Magistrale in Ingegneria Informatica",
        "Diplôme d'Ingénieur",
        "Máster Universitario en Ciencia de Datos",
        "Magister (mgr)",
        "工学硕士",
        "修士（情報学）",
        "공학석사",
    ):
        assert degree_level(deg) == "master", deg
        assert _is_master_qualification(deg), deg

    assert (
        infer_local_credits_per_year(
            [Decimal("6")] * 40,
            total_credits=Decimal("240"),
            qualification="Grado en Ingeniería Informática",
            country_code="ES",
        )
        == Decimal("60")
    )
    assert (
        infer_local_credits_per_year(
            [Decimal("6")] * 24,
            total_credits=Decimal("240"),
            qualification="Grado en Ingeniería Informática",
            country_code="ES",
        )
        == Decimal("36")
    )


def test_group4_mrz_and_id_reading_cross_script_patronymic_and_compound_given() -> None:
    assert mrz.same_name_token("Алиева", "Aliyeva")
    assert mrz.same_given_name("Иван", "Ivan")
    assert not mrz.same_given_name("Иван", "Пётр")
    assert mrz.name_keys("Kamil\u04d9") == mrz.name_keys("Kamilə")

    words, count = id_reading._known_words("Ahmad bin Ali")
    assert words == ["Ahmad", "Ali"] and count == 3

    # Compound given names on passport ("MARIE JEAN") vs profile ("Jean Dupont")
    values = [
        id_reading.ReadValue("identity.given_names", "MARIE JEAN", "MARIE JEAN", True, "mrz"),
        id_reading.ReadValue("identity.surname", "DUPONT", "DUPONT", True, "mrz"),
    ]
    assert id_reading._owner_matches(values, ["Jean Dupont"])

    # Single-field mononym passport
    mono_values = [
        id_reading.ReadValue("identity.surname", "SUKARNO", "SUKARNO", True, "mrz"),
    ]
    assert id_reading._owner_matches(mono_values, ["Sukarno"])


def test_group4_text_reading_dates_europass_and_table() -> None:
    stripped = text_reading.strip_identifiers(
        "Сертификат выдан Алиева Нигяр.", ["Aliyeva", "Nigar"]
    )
    assert "Алиева" not in stripped
    assert "[REDACTED]" in stripped

    assert text_reading._iso_date("2025年07月15日") == "2025-07-15"
    assert text_reading._iso_date("2025년 7월 15일") == "2025-07-15"
    assert "Goethe-Zertifikat" in text_reading.TESTS
    assert "SIELE" in text_reading.TESTS

    assert dates.parse_cv_date("сентябрь 2022") == date(2022, 9, 1)
    assert dates.parse_cv_date("septiembre 2022") == date(2022, 9, 1)

    assert _language_code("Türkçe") == "tur"
    assert _language_code("Azərbaycanca") == "aze"
    assert _language_code("Deutsch") == "deu"
    assert _language_code("中文") == "zho"
    assert _language_code("Kazakh") == "kaz"
    assert _language_code("Swahili") == "swa"
    with pytest.raises(EuropassUnavailable):
        _language_code("Klingon")

    assert "TRANSCRIPT" in kinds_named("Bitte reichen Sie einen aktuellen Notenspiegel ein.")
    assert "MOTIVATION_LETTER" in kinds_named("Veuillez joindre une lettre de motivation.")
    assert "REFERENCE_LETTER" in kinds_named("İki adet referans mektubu gereklidir.")
    assert _CERTIFIED.search("amtlich beglaubigte Kopie")
    assert _CERTIFIED.search("noter onaylı suret")


def test_group4_research_fit_and_evidence_signals() -> None:
    assert "kowalski" not in guard_phrase(
        "quantum optics with Łukasz Kowalski", banned=frozenset()
    )
    assert "петров" not in guard_phrase(
        "катализ под руководством Иван Петров", banned=frozenset()
    )
    assert "universitat" not in strip_named_runs(
        "Computer Science at Łukaszewicz Universität"
    ).lower()

    sents = page_sentences(
        ["Prof. Dr. Ł. Kowalski researches optics. Ř. Novák leads the group."]
    )
    assert len(sents) == 2
    cjk_sents = page_sentences(
        ["本实验室致力于分布式系统与机器学习编译器的研究。由张伟教授主持相关课题。"]
    )
    assert len(cjk_sents) == 2

    for inactive in (
        "Prof. Jean Moreau, professeur émérite",
        "Prof. dr. ir. J. de Vries (met emeritaat)",
        "Prof. Marco Rossi (in pensione)",
        "Prof. Dr. Ahmet Yılmaz (Emekli Öğretim Üyesi)",
        "Проф. И. Петров, почетный профессор",
        "山田太郎 名誉教授",
        "김철수 명예교수",
    ):
        assert _INACTIVE_PERSON_RE.search(inactive), inactive

    assert author_in_byline("Zhang Wei", ("Wei Zhang", "A. Other"))
    assert author_in_byline("Zhang Wei", ("W. Zhang",))
    assert author_in_byline("Kovács János", ("János Kovács",))
    assert author_in_byline("Carlos García López", ("Carlos García",))
    assert not author_in_byline("Jane Smith", ("Jane Doe",))

    assert person_matches_author("Prof. Dr. Zhang Wei", ("Wei Zhang",))
    assert person_matches_author("Prof. Dr. Kovács János", ("J. Kovács",))
    assert person_matches_author("Prof. Dr. Carlos García López", ("C. García",))
    assert not person_matches_author("Prof. Jane Smith", ("Jane Doe",))

    pyproject = """
[project]
name = "demo"
dependencies = ["numpy>=2.0", "scipy[optimize]>=1.12; python_version>='3.11'"]

[tool.poetry.dependencies]
python = "^3.12"
jax = "^0.4"
"""
    assert manifest_libraries("pyproject.toml", pyproject) == ("jax", "numpy", "scipy")

    rust_src = """//! High-performance graph routing kernel.

/// Computes shortest path over weighted edges.
pub fn shortest_path(n: usize) -> usize {
    n
}
"""
    rs_sig = file_signals("src/lib.rs", rust_src)
    assert rs_sig.module_doc == "High-performance graph routing kernel."
    assert rs_sig.definitions == (
        ("shortest_path", "Computes shortest path over weighted edges."),
    )
    assert "src/lib.rs" in interesting_paths(("src/lib.rs",), limit=5)
