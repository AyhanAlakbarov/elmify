"""Extract programme/scholarship eligibility rules and check them against the student's
profile and transcript courses, showing the exact courses and facts counted by us.

Covers the seven eligibility domains:
1. Subject-specific & coursework credit requirements (single bucket, conjunctive multi-bucket
   with anti-double-counting, combined pool with sub-floors, named-topic checklists, course/
   semester counts, non-ECTS credit conversions, conditional bridging deficits, failed/retaken
   course filtering, in-progress course separation, borderline/omnibus course intervals, and
   multilingual course titles in EN/DE/RU/AZ/TR).
2. Total prior-degree credit floors (180 / 210 / 240 ECTS).
3. GPA & cross-scale grade floors (same-scale, German inverted LTE, Modified Bavarian formula).
4. Language floors (exact numeric test score before CEFR, per-band subscores, MOI/country waivers).
5. Standardized tests (GRE Quantitative/Verbal/AWA, GMAT, with GPA/region waivers).
6. Work experience (professional work vs. internships, months/years).
7. Graduation timing & recency windows.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, replace
from datetime import date as _date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from apps.documents.credits import to_ects
from apps.funding.regions import REGIONS

VerdictOutcome = Literal[
    "SATISFIED",
    "BORDERLINE",
    "IN_PROGRESS",
    "CONDITIONAL_BRIDGE",
    "FAILED",
    "UNDECIDABLE",
]

CourseMatchStrength = Literal["DEFINITE", "BORDERLINE", "UNRELATED"]

_CENT = Decimal("0.01")
_ZERO = Decimal("0")


@dataclass(frozen=True)
class NormalizedCourse:
    """A passing or in-progress transcript course after failed/withdrawn filtering
    and same-degree retake deduplication."""

    title: str
    ects: Decimal | None
    grade: str | None
    in_progress: bool
    degree_index: int = 0
    degree_field: str = ""
    description: str | None = None


@dataclass(frozen=True)
class CountedCourse:
    """One transcript course allocated to a requirement bucket, with the ECTS counted."""

    title: str
    ects: Decimal | None
    allocated_ects: Decimal
    strength: Literal["DEFINITE", "BORDERLINE"]
    in_progress: bool = False


@dataclass(frozen=True)
class SubjectBucketRule:
    """One subject credit or course-count bucket extracted from a statement."""

    subject_label: str
    subject_keys: tuple[str, ...]
    min_ects: Decimal | None = None
    min_courses: int | None = None
    allowed_deficit_ects: Decimal = _ZERO
    required_topics: tuple[str, ...] = ()
    is_subfloor_of_pool: bool = False


@dataclass(frozen=True)
class SubjectPoolRule:
    """A conjunctive or disjunctive set of subject buckets, optionally wrapped in a parent pool."""

    buckets: tuple[SubjectBucketRule, ...]
    pool_min_ects: Decimal | None = None
    pool_subject_label: str = ""
    pool_subject_keys: tuple[str, ...] = ()
    allowed_deficit_ects: Decimal = _ZERO
    combinator: Literal["AND", "OR"] = "AND"


@dataclass(frozen=True)
class StatementEvaluation:
    """The result of checking one programme/scholarship requirement statement against a profile."""

    outcome: VerdictOutcome
    status_text: str
    counted_courses: tuple[CountedCourse, ...] = ()
    completed_definite_ects: Decimal = _ZERO
    completed_possible_ects: Decimal = _ZERO
    in_progress_ects: Decimal = _ZERO
    required_ects: Decimal | None = None
    missing_topics: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# 1. Course Filtering (Failed / Withdrawn) & Retake Deduplication
# ---------------------------------------------------------------------------

_EXACT_FAILING_GRADES: frozenset[str] = frozenset(
    {
        "f", "fx", "ff", "fd", "np", "u", "w", "wd", "wf", "wu", "nc", "dna", "abs",
        "fail", "failed", "withdrawn", "incomplete", "inc", "0", "0.0", "0,0", "0.00",
        "kəsr", "qeyri-kafi", "qeyri kafi", "q/k", "qk",
        "başarısız", "basarisiz", "kaldı", "kaldi", "devamsız", "devamsiz", "dz", "na",
        "не зачтено", "незачет", "незачёт", "неудовлетворительно", "неуд", "неуд.",
        "не явился", "н/я",
        "nicht bestanden", "nb", "n.b.", "ungenügend", "ungenugend", "mangelhaft",
    }
)

_PASSING_WORD_GRADES: frozenset[str] = frozenset(
    {
        "p", "s", "cr", "pass", "passed",
        "зачтено", "зачет", "зачёт", "отлично", "хорошо", "удовлетворительно",
        "bestanden", "b", "sehr gut", "gut", "befriedigend", "ausreichend",
        "məqbul", "meqbul", "əla", "yaxşı", "kafi",
        "muaf", "geçti", "gecti", "başarılı",
    }
)

_RETAKE_TAG_RE = re.compile(
    r"\s*[\(\[\-–—]\s*(?:retake|repeat|repeated|resit|tekrar|повтор(?:но)?|"
    r"təkrar|wiederholung)\s*[\)\]]?\s*$",
    re.IGNORECASE,
)


def _parse_decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    cleaned = raw.strip().rstrip("%").strip()
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    if not re.match(r"^[+-]?\d+(?:\.\d+)?$", cleaned):
        return None
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def _is_german_inverted_scale(grading_scale: str, country_code: str = "") -> bool:
    s = grading_scale.casefold().strip()
    cc = country_code.strip().upper()
    if any(
        tok in s
        for tok in (
            "1.0-5.0",
            "1.0-4.0",
            "1,0-4,0",
            "1,0-5,0",
            "german",
            "bavarian",
            "austrian",
            "österreich",
        )
    ):
        return True
    if "1-5" in s and cc not in {"RU", "KZ", "BY", "UA", "UZ", "KG", "TJ", "TM", "NG", "SA"}:
        return True
    return cc in {"DE", "AT"} and s in {"5", "5.0", "4", "4.0"}


def is_failing_or_withdrawn_grade(
    grade: str | None,
    grading_scale: str | None = "",
    country_code: str | None = "",
) -> bool:
    """Return True if `grade` represents a failed, withdrawn, or uncredited attempt."""
    if grade is None:
        return False
    folded = " ".join(grade.strip().split()).casefold()
    if not folded or folded in ("-", "—", "n/a", "none", "not stated", "unknown"):
        return False
    if folded in _PASSING_WORD_GRADES:
        return False
    if folded in _EXACT_FAILING_GRADES:
        return True
    if re.match(
        r"^(?:f|fx|ff|fd|np|u|w|wd|wf|wu|nc|dna|abs|dz|na|nb)(?:\s*[\(\[\-–/:].*)?$",
        folded,
    ):
        return True
    if any(
        marker in folded
        for marker in (
            "nicht bestanden",
            "mangelhaft",
            "ungenügend",
            "ungenugend",
            "не зачтено",
            "неудовлетворительно",
            "qeyri-kafi",
            "başarısız",
            "withdrawn",
            "failed",
        )
    ):
        return True

    cc = (country_code or "").strip().upper()
    num = _parse_decimal(folded)
    eff_scale = (grading_scale or "").strip()
    if num is None:
        m_slash = re.match(
            r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)\b",
            folded,
        )
        if m_slash:
            num = _parse_decimal(m_slash.group(1))
            if not eff_scale.strip():
                eff_scale = m_slash.group(2)
        else:
            m_lead = re.match(
                r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*(%)?(?:\s*[\(\[\-–—]|\s+[a-zA-Z])",
                folded,
            )
            if m_lead:
                num = _parse_decimal(m_lead.group(1))
                if not eff_scale.strip() and m_lead.group(2):
                    eff_scale = "100"

    if num is not None:
        if num <= _ZERO:
            return True
        if _is_german_inverted_scale(eff_scale, cc):
            return num > Decimal("4.0")
        bounds = _parse_scale_bounds(eff_scale, cc)
        if bounds is not None:
            max_g, min_pass, has_explicit_min = bounds
            if max_g in (Decimal("4.0"), Decimal("4.3"), Decimal("4.5")):
                # On a 4.0/4.3/4.5 GPA scale, a single course with D (1.0) earns credit;
                # only 0.0 (F) fails the course unless an explicit range floor was stated.
                return num < min_pass if has_explicit_min else False
            if max_g == Decimal("100") and not has_explicit_min:
                if cc in {"GB", "UK", "IE", "AU", "NZ"}:
                    return num < Decimal("40")
                if cc == "CN":
                    return num < Decimal("60")
                if cc == "AZ":
                    return num < Decimal("51")
                return num < Decimal("50")
            if max_g == Decimal("10") and not has_explicit_min and cc == "NL":
                return num < Decimal("5.5")
            return num < min_pass
    return False


def _course_dedup_key(title: str) -> str:
    """Canonical key for deduplicating retaken courses within the same degree record.
    Strips trailing retake markers while preserving Roman/Arabic part numbers (I, II, 1, 2)."""
    cleaned = _RETAKE_TAG_RE.sub("", title.strip())
    cleaned = re.sub(r"[^\w\s]", " ", cleaned.casefold())
    return " ".join(cleaned.split())


def normalize_transcript_courses(profile: object) -> tuple[NormalizedCourse, ...]:
    """Extract, filter (dropping failed/withdrawn attempts), and deduplicate (merging retakes
    within each degree) all courses from `profile.academic_history`."""
    records = tuple(getattr(profile, "academic_history", ()) or ())
    result: list[NormalizedCourse] = []

    for deg_idx, record in enumerate(records):
        grading_scale = str(getattr(record, "grading_scale", "") or "")
        country_code = str(getattr(record, "country_code", "") or "")
        degree_field = str(getattr(record, "field", "") or "")
        raw_courses = tuple(getattr(record, "courses", ()) or ())
        by_key: dict[str, NormalizedCourse] = {}

        for raw in raw_courses:
            title = str(getattr(raw, "title", "") or "").strip()
            if not title:
                continue
            grade = getattr(raw, "grade", None)
            grade_str = str(grade).strip() if grade is not None else None
            in_prog = bool(getattr(raw, "in_progress", False))

            if not in_prog and is_failing_or_withdrawn_grade(
                grade_str, grading_scale, country_code
            ):
                continue

            raw_ects = getattr(raw, "ects", None)
            ects_val: Decimal | None = None
            if isinstance(raw_ects, Decimal):
                ects_val = raw_ects
            elif raw_ects is not None:
                ects_val = _parse_decimal(str(raw_ects))

            raw_desc = getattr(raw, "description", None)
            desc_str = (
                str(raw_desc).strip()
                if raw_desc is not None and str(raw_desc).strip()
                else None
            )

            candidate = NormalizedCourse(
                title=_RETAKE_TAG_RE.sub("", title).strip() or title,
                ects=ects_val,
                grade=grade_str,
                in_progress=in_prog,
                degree_index=deg_idx,
                degree_field=degree_field,
                description=desc_str,
            )

            dedup_key = _course_dedup_key(title)
            existing = by_key.get(dedup_key)
            if existing is None:
                by_key[dedup_key] = candidate
            elif existing.in_progress and not candidate.in_progress:
                by_key[dedup_key] = (
                    candidate
                    if candidate.description is not None or existing.description is None
                    else replace(candidate, description=existing.description)
                )
            elif existing.in_progress == candidate.in_progress:
                if candidate.ects is not None or existing.ects is None:
                    by_key[dedup_key] = (
                        candidate
                        if candidate.description is not None or existing.description is None
                        else replace(candidate, description=existing.description)
                    )

        result.extend(by_key.values())

    return tuple(result)


# ---------------------------------------------------------------------------
# 2. Multilingual Subject Taxonomy & Course-to-Subject Classifier
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _SubjectTaxonomyEntry:
    key: str
    aliases: tuple[str, ...]
    definite_patterns: tuple[str, ...]
    borderline_patterns: tuple[str, ...] = ()
    parent_keys: tuple[str, ...] = ()


_SUBJECT_TAXONOMY: tuple[_SubjectTaxonomyEntry, ...] = (
    _SubjectTaxonomyEntry(
        key="THEORETICAL_CS",
        aliases=(
            "theoretical computer science", "theoretical informatics", "theoretische informatik",
            "theoretischer informatik", "theory of computation", "computer science theory",
            "formal methods", "algorithms and theory", "теоретическая информатика",
            "nəzəri informatika", "kuramsal bilgisayar bilimi",
        ),
        definite_patterns=(
            # English
            "theoretical computer science", "theory of computation", "automata",
            "formal language", "formal languages", "computability", "complexity theory",
            "computational complexity", "algorithm", "algorithms", "data structure",
            "data structures", "discrete math", "discrete mathematics", "discrete structure",
            "discrete structures", "graph theory", "combinatorics", "mathematical logic",
            "logic in computer science", "formal logic", "propositional logic",
            "predicate logic", "computational logic", "formal methods", "formal verification",
            "model checking", "program verification", "type theory", "lambda calculus",
            "semantics of programming", "cryptography", "cryptology", "coding theory",
            "information theory", "compiler", "compilers", "quantum computing",
            "quantum information", "computational geometry", "randomized algorithms",
            "approximation algorithms", "parameterized complexity", "petri nets",
            # German
            "theoretische informatik", "automaten", "formale sprachen", "berechenbarkeit",
            "komplexität", "komplexitaet", "algorithmen", "datenstrukturen",
            "diskrete mathematik", "diskrete strukturen", "graphentheorie", "kombinatorik",
            "logik", "formale methoden", "formale verifikation", "modellprüfung",
            "kryptographie", "kryptologie", "codierungstheorie", "informationstheorie",
            "compilerbau", "übersetzerbau",
            # Russian
            "теоретическая информатика", "теория алгоритмов", "алгоритм", "структуры данных",
            "автомат", "формальные языки", "вычислимость", "сложность вычислений",
            "дискретная математика", "дискретные структуры", "теория графов", "комбинаторика",
            "математическая логика", "формальная верификация", "криптография",
            "теория кодирования", "теория информации", "методы трансляции", "компилятор",
            # Azerbaijani
            "nəzəri informatika", "alqoritm", "verilənlər strukturu", "diskret riyaziyyat",
            "avtomatlar", "formal dillər", "hesablanma mürəkkəbliyi", "qraflar nəzəriyyəsi",
            "kombinatorika", "riyazi məntiq", "kriptoqrafiya", "informasiya nəzəriyyəsi",
            "kompilyator",
            # Turkish
            "kuramsal bilgisayar", "otomata", "biçimsel diller", "algoritma", "veri yapıları",
            "ayrık matematik", "hesaplama kuramı", "karmaşıklık", "çizge kuramı",
            "kombinatorik", "mantık", "kriptografi", "bilgi kuramı", "derleyici",
        ),
        borderline_patterns=(
            "foundations of computer science", "foundations of informatics",
            "computer science i", "computer science ii", "introduction to computer science",
            "grundlagen der informatik", "informatik i", "informatik ii", "informatik 1",
            "informatik 2", "numerical methods", "numerical analysis", "operations research",
            "optimization", "special topics in computer science", "введение в информатику",
            "основы информатики", "informatikanın əsasları", "bilgisayar bilimine giriş",
        ),
        parent_keys=("COMPUTER_SCIENCE",),
    ),
    _SubjectTaxonomyEntry(
        key="COMPUTER_SCIENCE",
        aliases=(
            "computer science", "informatics", "computing", "informatik",
            "software engineering", "programming", "computer engineering",
            "information technology", "информатика", "компьютерные науки", "программирование",
            "informatika", "kompüter elmləri", "bilgisayar mühendisliği", "bilgisayar bilimi",
        ),
        definite_patterns=(
            "computer science", "informatics", "informatik", "programming", "object-oriented",
            "functional programming", "software engineering", "software architecture",
            "software testing", "operating system", "operating systems", "computer network",
            "computer networks", "distributed systems", "parallel computing", "database",
            "databases", "computer architecture", "computer organization", "embedded systems",
            "machine learning", "deep learning", "artificial intelligence", "neural networks",
            "computer vision", "natural language processing", "data mining", "data science",
            "big data", "cybersecurity", "information security", "network security",
            "computer graphics", "human-computer interaction", "web development",
            "cloud computing",
            "programmierung", "softwaretechnik", "betriebssysteme", "rechnernetze",
            "datenbanken", "rechnerarchitektur", "verteilte systeme", "künstliche intelligenz",
            "maschinelles lernen", "it-sicherheit",
            "программирование", "программная инженерия", "операционные системы",
            "компьютерные сети", "базы данных", "архитектура эвм", "архитектура компьютера",
            "распределенные системы", "машинное обучение", "искусственный интеллект",
            "информационная безопасность",
            "proqramlaşdırma", "proqram mühəndisliyi", "əməliyyat sistemləri",
            "kompüter şəbəkələri", "verilənlər bazası", "kompüter arxitekturası",
            "süni intellekt", "maşın öyrənməsi", "informasiya təhlükəsizliyi",
            "programlama", "yazılım mühendisliği", "işletim sistemleri", "bilgisayar ağları",
            "veritabanı", "bilgisayar mimarisi", "yapay zeka", "makine öğrenmesi",
            "bilgi güvenliği",
        ),
        borderline_patterns=(
            "bachelor thesis", "bachelor's thesis", "bachelorarbeit", "senior project",
            "capstone project", "graduation project", "выпускная квалификационная работа",
            "дипломная работа", "buraxılış işi", "bitirme projesi", "information systems",
            "digital systems", "bioinformatics",
        ),
    ),
    _SubjectTaxonomyEntry(
        key="MATHEMATICS",
        aliases=(
            "mathematics", "math", "maths", "pure mathematics", "applied mathematics",
            "higher mathematics", "mathematik", "reiner mathematik", "angewandter mathematik",
            "höherer mathematik", "математика", "высшая математика",
            "riyaziyyat", "ali riyaziyyat", "matematik",
        ),
        definite_patterns=(
            "mathematics", "calculus", "real analysis", "complex analysis",
            "mathematical analysis", "analysis i", "analysis ii", "analysis iii",
            "analysis 1", "analysis 2", "linear algebra", "abstract algebra", "algebra",
            "differential equations", "ordinary differential equations",
            "partial differential equations", "probability", "mathematical statistics",
            "stochastics", "stochastic processes", "numerical analysis", "numerical methods",
            "discrete mathematics", "discrete structures", "graph theory", "combinatorics",
            "topology", "differential geometry", "geometry", "measure theory",
            "functional analysis", "number theory", "optimization", "operations research",
            "vector calculus", "multivariable calculus", "mathematical logic",
            "mathematik", "höhere mathematik", "lineare algebra", "analysis",
            "differentialgleichungen", "wahrscheinlichkeitstheorie", "stochastik", "numerik",
            "numerische mathematik", "funktionalanalysis", "maßtheorie", "topologie",
            "zahlentheorie", "optimierung",
            "математический анализ", "высшая математика", "математика", "линейная алгебра",
            "алгебра и геометрия", "дифференциальные уравнения", "теория вероятностей",
            "математическая статистика", "численные методы", "функциональный анализ",
            "теория чисел", "топология", "методы оптимизации", "исследование операций",
            "riyazi analiz", "ali riyaziyyat", "riyaziyyat", "xətti cəbr", "cəbr və həndəsə",
            "diferensial tənliklər", "ehtimal nəzəriyyəsi", "riyazi statistika",
            "ədədi üsullar", "funksional analiz", "optimallaşdırma",
            "matematik", "kalkülüs", "analiz", "lineer cebir", "doğrusal cebir",
            "diferansiyel denklemler", "olasılık", "matematiksel istatistik",
            "sayısal yöntemler", "sayısal analiz", "optimizasyon", "yöneylem araştırması",
        ),
        borderline_patterns=(
            "quantitative methods", "econometrics", "biostatistics", "mathematical physics",
            "computational physics",
        ),
    ),
    _SubjectTaxonomyEntry(
        key="STATISTICS_ECONOMETRICS",
        aliases=(
            "statistics", "econometrics", "quantitative methods", "statistical methods",
            "data analysis", "statistik", "ökonometrie", "статистика", "эконометрика",
            "statistika", "ekonometrika", "istatistik", "ekonometri",
        ),
        definite_patterns=(
            "statistics", "statistical", "probability", "econometrics", "time series",
            "regression", "stochastic", "biostatistics", "bayesian", "quantitative methods",
            "data analysis", "experimental design", "multivariate analysis", "statistik",
            "ökonometrie", "wahrscheinlichkeit", "статистика", "эконометрика",
            "теория вероятностей", "statistika", "ekonometrika", "ehtimal", "istatistik",
            "ekonometri", "olasılık",
        ),
        borderline_patterns=("data science", "machine learning", "research methods"),
    ),
    _SubjectTaxonomyEntry(
        key="ECONOMICS_BUSINESS",
        aliases=(
            "economics", "business administration", "business", "finance", "management",
            "accounting", "volkswirtschaftslehre", "betriebswirtschaftslehre",
            "wirtschaftswissenschaften", "экономика", "менеджмент", "финансы",
            "iqtisadiyyat", "maliyyə", "idarəetmə", "iktisat", "işletme", "finans",
        ),
        definite_patterns=(
            "microeconomics", "macroeconomics", "economics", "econometrics", "finance",
            "corporate finance", "financial markets", "accounting", "financial accounting",
            "managerial accounting", "business administration", "management",
            "strategic management", "operations management", "marketing",
            "international trade", "public finance", "game theory", "industrial organization",
            "volkswirtschaft", "betriebswirtschaft", "mikroökonomie", "makroökonomie",
            "finanzwirtschaft", "rechnungswesen",
            "микроэкономика", "макроэкономика", "экономика", "финансы", "бухгалтерский учет",
            "менеджмент", "маркетинг",
            "mikroiqtisadiyyat", "makroiqtisadiyyat", "iqtisadiyyat", "maliyyə", "mühasibat",
            "menecment", "marketinq",
            "mikroekonomi", "makroekonomi", "iktisat", "işletme", "finans", "muhasebe",
            "pazarlama",
        ),
    ),
    _SubjectTaxonomyEntry(
        key="PHYSICS",
        aliases=("physics", "physik", "физика", "fizika", "fizik"),
        definite_patterns=(
            "physics", "classical mechanics", "quantum mechanics", "quantum physics",
            "electrodynamics", "electromagnetism", "thermodynamics", "statistical mechanics",
            "statistical physics", "optics", "solid state physics", "condensed matter",
            "nuclear physics", "particle physics", "astrophysics", "relativity", "physik",
            "quantenmechanik", "elektrodynamik", "thermodynamik", "физика",
            "квантовая механика", "электродинамика", "термодинамика", "оптика", "fizika",
            "kvant mexanikası", "termodinamika", "fizik", "kuantum mekaniği",
        ),
    ),
    _SubjectTaxonomyEntry(
        key="CHEMISTRY",
        aliases=("chemistry", "chemie", "химия", "kimya"),
        definite_patterns=(
            "chemistry", "organic chemistry", "inorganic chemistry", "physical chemistry",
            "analytical chemistry", "biochemistry", "polymer chemistry", "chemie",
            "organische chemie", "anorganische chemie", "physikalische chemie", "химия",
            "органическая химия", "неорганическая химия", "физическая химия",
            "аналитическая химия", "биохимия", "kimya", "üzvi kimya", "qeyri-üzvi kimya",
            "fiziki kimya", "analitik kimya", "biokimya", "organik kimya", "anorganik kimya",
        ),
    ),
    _SubjectTaxonomyEntry(
        key="BIOLOGY_LIFE_SCIENCES",
        aliases=(
            "biology", "life sciences", "molecular biology", "biotechnology", "genetics",
            "biologie", "биология", "biologiya", "biyoloji",
        ),
        definite_patterns=(
            "biology", "molecular biology", "cell biology", "genetics", "genomics",
            "microbiology", "immunology", "biochemistry", "biotechnology", "neuroscience",
            "neurobiology", "physiology", "ecology", "evolution", "bioinformatics",
            "biologie", "molekularbiologie", "genetik", "mikrobiologie", "биология",
            "молекулярная биология", "генетика", "микробиология", "биотехнология",
            "biologiya", "molekulyar biologiya", "genetika", "mikrobiologiya",
            "biotexnologiya", "biyoloji", "moleküler biyoloji",
        ),
    ),
    _SubjectTaxonomyEntry(
        key="ELECTRICAL_ENGINEERING",
        aliases=(
            "electrical engineering", "electronics", "telecommunications", "elektrotechnik",
            "электротехника", "радиотехника", "elektrik mühəndisliyi",
            "elektrik-elektronik mühendisliği",
        ),
        definite_patterns=(
            "circuit", "circuits", "electronics", "digital electronics", "analog electronics",
            "signals and systems", "signal processing", "digital signal processing",
            "control systems", "control theory", "electromagnetics", "power systems",
            "power electronics", "microprocessors", "embedded systems", "vlsi",
            "telecommunications", "communication systems", "elektrotechnik",
            "schaltungstechnik", "signale und systeme", "regelungstechnik", "электроника",
            "теория цепей", "сигналы и системы", "теория управления", "микропроцессор",
            "elektronika", "sxemotexnika", "siqnallar və sistemlər", "devre teorisi",
            "sinyaller ve sistemler", "kontrol sistemleri",
        ),
    ),
)

_TAXONOMY_BY_KEY: dict[str, _SubjectTaxonomyEntry] = {
    entry.key: entry for entry in _SUBJECT_TAXONOMY
}

_LETTER_BOUNDARY_LEFT = r"(?<![a-zA-Zа-яА-ЯёЁəƏıİöÖüÜçÇşŞğĞ])"
_LETTER_BOUNDARY_RIGHT = r"(?![a-zA-Zа-яА-ЯёЁəƏıİöÖüÜçÇşŞğĞ])"


def resolve_subject_keys(subject_phrase: str) -> tuple[str, ...]:
    """Map a natural-language subject phrase (e.g. 'theoretical computer science',
    'mathematics or statistics') to one or more canonical taxonomy keys, or a normalized
    custom phrase token when outside the predefined table."""
    cleaned = " ".join(subject_phrase.strip().split()).casefold()
    if not cleaned:
        return ()

    matched_keys: list[str] = []
    all_alias_pairs: list[tuple[str, str]] = [
        (alias, entry.key) for entry in _SUBJECT_TAXONOMY for alias in entry.aliases
    ]
    all_alias_pairs.sort(key=lambda pair: len(pair[0]), reverse=True)

    remaining = cleaned
    for alias, key in all_alias_pairs:
        pattern = _LETTER_BOUNDARY_LEFT + re.escape(alias) + _LETTER_BOUNDARY_RIGHT
        if re.search(pattern, remaining):
            if key not in matched_keys:
                matched_keys.append(key)
            remaining = re.sub(pattern, " ", remaining)

    if matched_keys:
        return tuple(matched_keys)
    return (f"CUSTOM:{cleaned}",)


def _pattern_in_title(title_folded: str, pattern: str) -> bool:
    regex = _LETTER_BOUNDARY_LEFT + re.escape(pattern) + _LETTER_BOUNDARY_RIGHT
    return bool(re.search(regex, title_folded))


def _classify_text_for_subject(
    text_folded: str,
    subject_keys: tuple[str, ...],
) -> CourseMatchStrength:
    if not text_folded:
        return "UNRELATED"

    best: CourseMatchStrength = "UNRELATED"

    for key in subject_keys:
        if key.startswith("CUSTOM:"):
            custom_phrase = key.removeprefix("CUSTOM:").strip()
            if custom_phrase and _pattern_in_title(text_folded, custom_phrase):
                return "DEFINITE"
            words = [
                w
                for w in re.split(r"\W+", custom_phrase)
                if len(w) >= 4 and w not in {"courses", "course", "subject", "studies", "field"}
            ]
            if words and all(_pattern_in_title(text_folded, w) for w in words):
                return "DEFINITE"
            if words and any(_pattern_in_title(text_folded, w) for w in words):
                best = "BORDERLINE"
            continue

        entry = _TAXONOMY_BY_KEY.get(key)
        if entry is None:
            continue

        if any(_pattern_in_title(text_folded, pat) for pat in entry.definite_patterns):
            return "DEFINITE"

        for child_entry in _SUBJECT_TAXONOMY:
            if key in child_entry.parent_keys:
                if any(
                    _pattern_in_title(text_folded, pat) for pat in child_entry.definite_patterns
                ):
                    return "DEFINITE"

        if any(_pattern_in_title(text_folded, pat) for pat in entry.borderline_patterns):
            best = "BORDERLINE"

    return best


def classify_course_for_subject(
    course: NormalizedCourse,
    subject_keys: tuple[str, ...],
) -> CourseMatchStrength:
    """Classify whether `course` belongs to any of `subject_keys` as `DEFINITE`,
    `BORDERLINE` (omnibus/broad/thesis course), or `UNRELATED`. When a course title
    is opaque or borderline (e.g. 'Special Topics in CS I' or 'Elective Module 3') and
    `course.description` is present, syllabus/description topics can upgrade the match."""
    title_folded = " ".join(course.title.strip().split()).casefold()
    title_strength = _classify_text_for_subject(title_folded, subject_keys)
    if title_strength == "DEFINITE" or not course.description:
        return title_strength

    desc_folded = " ".join(course.description.strip().split()).casefold()
    desc_strength = _classify_text_for_subject(desc_folded, subject_keys)
    if desc_strength == "DEFINITE":
        return "DEFINITE"
    if title_strength == "BORDERLINE" or desc_strength == "BORDERLINE":
        return "BORDERLINE"
    return "UNRELATED"


_TOPIC_SYNONYMS: dict[str, tuple[str, ...]] = {
    "linear algebra": (
        "lineare algebra", "линейная алгебра", "xətti cəbr", "lineer cebir", "doğrusal cebir",
    ),
    "calculus": (
        "analysis", "mathematik", "математический анализ", "высшая математика",
        "riyazi analiz", "ali riyaziyyat", "kalkülüs", "analiz",
    ),
    "analysis": (
        "calculus", "real analysis", "mathematical analysis", "математический анализ",
        "riyazi analiz", "analiz",
    ),
    "probability": (
        "wahrscheinlichkeit", "stochastik", "теория вероятностей", "ehtimal nəzəriyyəsi",
        "olasılık", "probability and statistics",
    ),
    "statistics": (
        "statistik", "статистика", "statistika", "istatistik", "probability and statistics",
    ),
    "algorithms": ("algorithmen", "алгоритм", "alqoritm", "algoritma"),
    "data structures": (
        "datenstrukturen", "структуры данных", "verilənlər strukturu", "veri yapıları",
    ),
    "discrete mathematics": (
        "discrete math", "discrete structures", "diskrete mathematik",
        "дискретная математика", "diskret riyaziyyat", "ayrık matematik",
    ),
    "operating systems": (
        "betriebssysteme", "операционные системы", "əməliyyat sistemləri",
        "işletim sistemleri",
    ),
    "databases": (
        "database", "datenbanken", "базы данных", "verilənlər bazası", "veritabanı",
    ),
    "software engineering": (
        "softwaretechnik", "программная инженерия", "proqram mühəndisliyi",
        "yazılım mühendisliği",
    ),
}


def course_matches_topic(course: NormalizedCourse, topic: str) -> bool:
    """Check whether `course` satisfies a named sub-topic (e.g. 'Linear Algebra', 'Probability')
    via its title or optional syllabus `description`."""
    topic_keys = resolve_subject_keys(topic)
    topic_folded = " ".join(topic.strip().split()).casefold()
    combined = f"{course.title} {course.description or ''}".strip()
    text_folded = " ".join(combined.split()).casefold()
    if not topic_folded or not text_folded:
        return False
    if _pattern_in_title(text_folded, topic_folded):
        return True
    for canonical, syns in _TOPIC_SYNONYMS.items():
        if canonical in topic_folded or any(s in topic_folded for s in syns):
            if _pattern_in_title(text_folded, canonical) or any(
                _pattern_in_title(text_folded, s) for s in syns
            ):
                return True
    if len(topic_keys) == 1 and not topic_keys[0].startswith("CUSTOM:"):
        if topic_folded in _TAXONOMY_BY_KEY[topic_keys[0]].aliases:
            return classify_course_for_subject(course, topic_keys) == "DEFINITE"
    return False


# ---------------------------------------------------------------------------
# 3. Extracting Subject-Credit & Coursework Rules from Programme Statements
# ---------------------------------------------------------------------------

_BRIDGING_DEFICIT_RE = re.compile(
    r"(?:missing|deficit\s+of|up\s+to|maximum\s+of|at\s+most|bis\s+zu)\s+"
    r"(\d{1,3}(?:[.,]\d+)?)\s*(?:ects|credits?|cp|lp|credit\s+points?)"
    r"[^.]{0,120}?(?:make\s+up|made\s+up|bridging|compensat|conditional|first\s+year|"
    r"within\s+one\s+year|nachhol|auflage)",
    re.IGNORECASE,
)

_BRIDGING_DEFICIT_REV_RE = re.compile(
    r"(?:make\s+up|compensate|complete|catch\s+up|nachholen)[^.]{0,60}?"
    r"(?:up\s+to|maximum\s+of|at\s+most|bis\s+zu)\s+"
    r"(\d{1,3}(?:[.,]\d+)?)\s*(?:ects|credits?|cp|lp)",
    re.IGNORECASE,
)

_TOTAL_DEGREE_CREDITS_RE = re.compile(
    r"(?:bachelor(?:'s)?\s+degree|undergraduate\s+degree|first\s+degree|prior\s+degree|"
    r"university\s+degree|qualification)(?:\s+in\s+[^,.;]{2,50}?)?\s+"
    r"(?:of|with|worth|comprising|totalling|totaling|carrying)?\s*"
    r"(?:at\s+least|minimum\s+of|min\.?\s*)?\s*"
    r"(180|210|240)\s*(?:ects(?:\s+credits?)?|credits?|cp|lp)\b"
    r"|\b(?:at\s+least|minimum\s+of|min\.?\s*)(180|210|240)\s*"
    r"(?:ects(?:\s+credits?)?|credits?|cp|lp)\s+(?:bachelor|undergraduate|degree)\b"
    r"|\b(?:at\s+least|minimum\s+of|min\.?\s*|comprising\s+)\s*(180|210|240)\s*"
    r"(?:ects(?:\s+credits?)?|credit\s+points?|cp|lp)\b"
    r"(?!\s+(?:in|of|from)\s+(?!a\s+bachelor|an\s+undergraduate|total\b))",
    re.IGNORECASE,
)

_UNIT_PAT = (
    r"((?:ects|cats|cp|lp|zet|зет|sch)(?:\s+credits?)?|"
    r"(?:us\s+)?quarter\s+(?:credits?|hours?)|"
    r"us\s+(?:semester\s+)?credits?(?:\s+hours?)?|"
    r"semester\s+(?:credit\s+)?hours?|credits?)"
)

_POOL_WITH_SUBFLOOR_RE = re.compile(
    r"(?:at\s+least|minimum\s+of|min\.?\s*)?\s*(\d{1,3}(?:[.,]\d+)?)\s*"
    + _UNIT_PAT
    + r"\s+(?:in|of|from|across)\s+([^,.;]+?)\s*,\s*"
    r"(?:of\s+which|including|thereof|whereof|davon)\s+"
    r"(.+)",
    re.IGNORECASE,
)

_BUCKET_ITEM_RE = re.compile(
    r"(?:at\s+least|minimum\s+of|min\.?\s*|mindestens\s+)?\s*(\d{1,3}(?:[.,]\d+)?)\s*"
    + _UNIT_PAT
    + r"\s*(?:must\s+be\s+)?(?:in|of|from|im\s+bereich|aus\s+dem\s+bereich|aus)\s+"
    r"([a-zA-Zа-яА-ЯёЁəƏıİöÖüÜçÇşŞğĞ][a-zA-Zа-яА-ЯёЁəƏıİöÖüÜçÇşŞğĞ\s/,&-]{2,90}?"
    r"(?:\s*\([^)]{3,120}\))?)"
    r"(?=(?:\s*(?:,\s*(?:and\b|or\b|oder\b|at\s+least\b|mindestens\b|\d|"
    r"a\b|an\b|the\b|with\b|minimum\b|min\b|gpa\b|cgpa\b|grade\b|overall\b|ielts\b|toefl\b)"
    r"|\s+(?:and|or|oder)\s+(?:at\s+least\s+|min\.?\s*|mindestens\s+|\d)"
    r"|\s*;\s*|\.|$|\(|\bmissing\b|\bapplicants\b)))",
    re.IGNORECASE,
)

_SUBJECT_FIRST_BUCKET_RE = re.compile(
    r"\b([a-zA-Zа-яА-ЯёЁəƏıİöÖüÜçÇşŞğĞ][a-zA-Zа-яА-ЯёЁəƏıİöÖüÜçÇşŞğĞ\s/&-]{2,70}?)\s*"
    r"(?::|—|–|-|\()\s*(?:at\s+least|minimum\s+of|min\.?\s*|mindestens\s*)?\s*"
    r"(\d{1,3}(?:[.,]\d+)?)\s*"
    + _UNIT_PAT
    + r"\b",
    re.IGNORECASE,
)

_TRAILING_VERB_RE = re.compile(
    r"\s+(?:(?:are|is|must\s+be|should\s+be|have\s+to\s+be|need\s+to\s+be)\s+"
    r"(?:required|completed|proven|needed|earned|acquired|demonstrated|fulfilled)"
    r"|required|needed|erforderlich|nachgewiesen\s+werden)\b.*$",
    re.IGNORECASE,
)

_TOPICS_PAREN_RE = re.compile(
    r"(?:\(\s*)?(?:covering|including|such\s+as|specifically|in\s+particular|namely)\s*"
    r"([a-zA-Z][a-zA-Z\s,/&-]{4,120}?)(?:\)|\.|$)"
    r"|\(\s*([a-zA-Z][a-zA-Z\s,/&-]{4,120}?)\s*\)",
    re.IGNORECASE,
)

_LEADING_TOPIC_INTRO_RE = re.compile(
    r"^(?:covering|including|such\s+as|specifically|in\s+particular|namely|e\.g\.?,?)\s+",
    re.IGNORECASE,
)

_COURSE_COUNT_RE = re.compile(
    r"(?:at\s+least|minimum\s+of|min\.?\s*)?\s*(\d{1,2})\s+"
    r"(?:university(?:-level)?\s+|undergraduate\s+)?"
    r"(courses?|modules?|semesters?)\s+(?:in|of)\s+"
    r"([a-zA-Z][a-zA-Z\s/,&-]{2,70}?)(?=[.;,()]|$)",
    re.IGNORECASE,
)


def _convert_stated_credits_to_ects(amount: Decimal, unit_token: str) -> Decimal:
    u = " ".join(unit_token.strip().split()).casefold()
    if "cats" in u:
        converted = to_ects(amount, "UK_CATS")
        return converted if converted is not None else amount
    if "quarter" in u:
        converted = to_ects(amount, "US_QUARTER_HOUR")
        return converted if converted is not None else amount
    if "zet" in u or "зет" in u:
        converted = to_ects(amount, "RU_ZET")
        return converted if converted is not None else amount
    if "eftsl" in u:
        converted = to_ects(amount, "AU_EFTSL")
        return converted if converted is not None else amount
    if "cbcs" in u:
        converted = to_ects(amount, "IN_CBCS")
        return converted if converted is not None else amount
    if "us " in u or "semester" in u or u in ("sch", "sch credits"):
        converted = to_ects(amount, "US_SEMESTER_HOUR")
        return converted if converted is not None else amount
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _clean_subject_label_and_topics(raw_subject: str) -> tuple[str, tuple[str, ...]]:
    text = raw_subject.strip().rstrip(".,;:")
    topics: list[str] = []

    m_topic = _TOPICS_PAREN_RE.search(text)
    if m_topic:
        raw_topics = m_topic.group(1) or m_topic.group(2) or ""
        text = text[: m_topic.start()].strip().rstrip(",(").strip()
        for part in re.split(r",|\band\b", raw_topics, flags=re.IGNORECASE):
            cleaned_topic = _LEADING_TOPIC_INTRO_RE.sub("", part.strip().strip("().")).strip()
            if cleaned_topic and len(cleaned_topic) >= 3:
                topics.append(cleaned_topic)

    text = _TRAILING_VERB_RE.sub("", text).strip()
    text = re.sub(
        r"\s+(?:courses?|modules?|subjects?|area|field|discipline)$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return text, tuple(topics)


def parse_subject_pool_rule(statement_text: str) -> SubjectPoolRule | None:
    """Extract a structured `SubjectPoolRule` from a natural-language competency statement,
    or return `None` if the statement is not a subject-credit / course-count rule."""
    text = " ".join(statement_text.strip().split())
    if not text:
        return None

    m_deg = _TOTAL_DEGREE_CREDITS_RE.search(text)
    if m_deg and len(_BUCKET_ITEM_RE.findall(text)) <= 1:
        only_matches = _BUCKET_ITEM_RE.findall(text)
        if not only_matches:
            return None
        amt_str, _, subj_str = only_matches[0]
        if amt_str in ("180", "210", "240") and any(
            w in subj_str.casefold() for w in ("bachelor", "degree", "total", "study")
        ):
            return None

    deficit = _ZERO
    m_def = _BRIDGING_DEFICIT_RE.search(text) or _BRIDGING_DEFICIT_REV_RE.search(text)
    if m_def:
        parsed_def = _parse_decimal(m_def.group(1))
        if parsed_def is not None:
            deficit = parsed_def

    m_pool = _POOL_WITH_SUBFLOOR_RE.search(text)
    if m_pool:
        pool_amt = _parse_decimal(m_pool.group(1))
        pool_unit = m_pool.group(2)
        pool_subj_raw = m_pool.group(3)
        sub_clause = m_pool.group(4)
        is_degree_preface = pool_amt in (
            Decimal("180"),
            Decimal("210"),
            Decimal("240"),
        ) and bool(
            re.search(
                r"\b(?:bachelor|undergraduate|degree|programme|study|total)\b",
                pool_subj_raw,
                re.IGNORECASE,
            )
        )
        if pool_amt is not None and not is_degree_preface:
            pool_ects = _convert_stated_credits_to_ects(pool_amt, pool_unit)
            pool_label, _ = _clean_subject_label_and_topics(pool_subj_raw)
            pool_keys = resolve_subject_keys(pool_label)
            sub_buckets: list[SubjectBucketRule] = []
            for b_amt_str, b_unit, b_subj_raw in _BUCKET_ITEM_RE.findall(sub_clause):
                b_amt = _parse_decimal(b_amt_str)
                if b_amt is None:
                    continue
                b_ects = _convert_stated_credits_to_ects(b_amt, b_unit)
                b_label, b_topics = _clean_subject_label_and_topics(b_subj_raw)
                b_keys = resolve_subject_keys(b_label)
                if b_keys:
                    sub_buckets.append(
                        SubjectBucketRule(
                            subject_label=b_label,
                            subject_keys=b_keys,
                            min_ects=b_ects,
                            allowed_deficit_ects=deficit,
                            required_topics=b_topics,
                            is_subfloor_of_pool=True,
                        )
                    )
            if sub_buckets:
                return SubjectPoolRule(
                    buckets=tuple(sub_buckets),
                    pool_min_ects=pool_ects,
                    pool_subject_label=pool_label,
                    pool_subject_keys=pool_keys,
                    allowed_deficit_ects=deficit,
                )

    bucket_matches = list(_BUCKET_ITEM_RE.finditer(text))
    buckets: list[SubjectBucketRule] = []
    for m_b in bucket_matches:
        b_amt_str, b_unit, b_subj_raw = m_b.group(1), m_b.group(2), m_b.group(3)
        b_amt = _parse_decimal(b_amt_str)
        if b_amt is None:
            continue
        if b_amt in (Decimal("180"), Decimal("210"), Decimal("240")) and re.search(
            r"\b(?:bachelor|undergraduate|degree|programme|total)\b", b_subj_raw, re.IGNORECASE
        ):
            continue
        b_ects = _convert_stated_credits_to_ects(b_amt, b_unit)
        b_label, b_topics = _clean_subject_label_and_topics(b_subj_raw)
        if not b_topics:
            m_paren = _TOPICS_PAREN_RE.search(text[m_b.start() :])
            if m_paren and len(bucket_matches) == 1:
                raw_t = m_paren.group(1)
                b_topics = tuple(
                    p.strip().strip("().")
                    for p in re.split(r",|\band\b", raw_t, flags=re.IGNORECASE)
                    if len(p.strip().strip("().")) >= 3
                )
        b_keys = resolve_subject_keys(b_label)
        if b_keys:
            buckets.append(
                SubjectBucketRule(
                    subject_label=b_label,
                    subject_keys=b_keys,
                    min_ects=b_ects,
                    allowed_deficit_ects=deficit,
                    required_topics=b_topics,
                )
            )

    if buckets:
        combinator: Literal["AND", "OR"] = "AND"
        if len(bucket_matches) >= 2:
            between = text[bucket_matches[0].end() : bucket_matches[1].start()]
            if re.search(r"\b(?:or|oder)\b", between, re.IGNORECASE):
                combinator = "OR"
        return SubjectPoolRule(
            buckets=tuple(buckets),
            allowed_deficit_ects=deficit,
            combinator=combinator,
        )

    # Check subject-first table/colon/parenthetical format ("Theoretical CS: at least 30 ECTS")
    for m_sf in _SUBJECT_FIRST_BUCKET_RE.finditer(text):
        sf_subj_raw, sf_amt_str, sf_unit = m_sf.group(1), m_sf.group(2), m_sf.group(3)
        sf_amt = _parse_decimal(sf_amt_str)
        if sf_amt is None or sf_amt in (Decimal("180"), Decimal("210"), Decimal("240")):
            continue
        sf_label, sf_topics = _clean_subject_label_and_topics(sf_subj_raw)
        if re.search(
            r"\b(?:bachelor|master|degree|programme|program|total|minimum|applicants)\b",
            sf_label,
            re.IGNORECASE,
        ):
            continue
        sf_keys = resolve_subject_keys(sf_label)
        if sf_keys:
            buckets.append(
                SubjectBucketRule(
                    subject_label=sf_label,
                    subject_keys=sf_keys,
                    min_ects=_convert_stated_credits_to_ects(sf_amt, sf_unit),
                    allowed_deficit_ects=deficit,
                    required_topics=sf_topics,
                )
            )
    if buckets:
        return SubjectPoolRule(buckets=tuple(buckets), allowed_deficit_ects=deficit)

    course_matches = _COURSE_COUNT_RE.findall(text)
    for count_str, _kind_word, c_subj_raw in course_matches:
        try:
            count_val = int(count_str)
        except ValueError:
            continue
        c_label, c_topics = _clean_subject_label_and_topics(c_subj_raw)
        c_keys = resolve_subject_keys(c_label)
        if c_keys and count_val > 0:
            buckets.append(
                SubjectBucketRule(
                    subject_label=c_label,
                    subject_keys=c_keys,
                    min_courses=count_val,
                    required_topics=c_topics,
                )
            )
    if buckets:
        return SubjectPoolRule(buckets=tuple(buckets))

    return None


# ---------------------------------------------------------------------------
# 4. Bipartite Anti-Double-Counting Allocation & Evaluation
# ---------------------------------------------------------------------------

def _fmt_ects(val: Decimal | None) -> str:
    if val is None:
        return "credits unstated"
    if val == val.to_integral_value():
        return f"{int(val)} ECTS"
    return f"{val.normalize()} ECTS"


def _fmt_num(val: Decimal) -> str:
    if val == val.to_integral_value():
        return str(int(val))
    return str(val.normalize())


def _format_course_list(courses: list[CountedCourse] | tuple[CountedCourse, ...]) -> str:
    if not courses:
        return "none on transcript"
    return ", ".join(
        f"{c.title} ({_fmt_ects(c.allocated_ects if c.ects is not None else None)})"
        for c in courses
    )


_OUTCOME_RANK: dict[VerdictOutcome, int] = {
    "SATISFIED": 6,
    "CONDITIONAL_BRIDGE": 5,
    "IN_PROGRESS": 4,
    "BORDERLINE": 3,
    "UNDECIDABLE": 2,
    "FAILED": 1,
}


def evaluate_subject_pool_rule(
    rule: SubjectPoolRule,
    courses: tuple[NormalizedCourse, ...],
) -> StatementEvaluation:
    """Evaluate a `SubjectPoolRule` against normalized transcript courses without double-counting
    any course's credits across conjunctive sibling buckets."""
    if not courses:
        return StatementEvaluation(
            outcome="UNDECIDABLE",
            status_text="Not yet checked — no transcript courses on your profile.",
        )

    if rule.combinator == "OR" and len(rule.buckets) > 1:
        alt_evals = [
            evaluate_subject_pool_rule(
                SubjectPoolRule(
                    buckets=(bucket,),
                    combinator="AND",
                    allowed_deficit_ects=rule.allowed_deficit_ects,
                ),
                courses,
            )
            for bucket in rule.buckets
        ]
        best_ev = max(
            alt_evals,
            key=lambda e: (_OUTCOME_RANK.get(e.outcome, 0), e.completed_definite_ects),
        )
        return StatementEvaluation(
            outcome=best_ev.outcome,
            status_text=" OR ".join(ev.status_text for ev in alt_evals),
            counted_courses=best_ev.counted_courses,
            completed_definite_ects=best_ev.completed_definite_ects,
            completed_possible_ects=best_ev.completed_possible_ects,
            in_progress_ects=best_ev.in_progress_ects,
            required_ects=best_ev.required_ects,
            missing_topics=best_ev.missing_topics,
        )

    remaining_ects: dict[int, Decimal] = {
        idx: (c.ects if c.ects is not None else _ZERO) for idx, c in enumerate(courses)
    }
    used_uncredited_indices: set[int] = set()

    matrix: dict[tuple[int, int], CourseMatchStrength] = {}
    for b_idx, bucket in enumerate(rule.buckets):
        for c_idx, course in enumerate(courses):
            matrix[(c_idx, b_idx)] = classify_course_for_subject(course, bucket.subject_keys)

    def _bucket_sort_key(b_idx: int) -> tuple[int, Decimal, int]:
        b_keys = set(rule.buckets[b_idx].subject_keys)
        parent_overlap = sum(
            1
            for k in b_keys
            if k in _TAXONOMY_BY_KEY
            for other_b_idx, other_b in enumerate(rule.buckets)
            if other_b_idx != b_idx
            and (set(_TAXONOMY_BY_KEY[k].parent_keys) & set(other_b.subject_keys))
        )
        total_supply = sum(
            (
                c.ects or _ZERO
                for c_idx, c in enumerate(courses)
                if matrix[(c_idx, b_idx)] == "DEFINITE"
            ),
            _ZERO,
        )
        return (-parent_overlap, total_supply, b_idx)

    bucket_order = sorted(range(len(rule.buckets)), key=_bucket_sort_key)
    bucket_allocations: list[list[CountedCourse]] = [[] for _ in rule.buckets]

    for stage_mode in ("EXCLUSIVE_DEFINITE", "SHARED_DEFINITE", "BORDERLINE"):
        for b_idx in bucket_order:
            bucket = rule.buckets[b_idx]
            for c_idx, course in enumerate(courses):
                strength = matrix[(c_idx, b_idx)]
                if stage_mode in ("EXCLUSIVE_DEFINITE", "SHARED_DEFINITE"):
                    if strength != "DEFINITE":
                        continue
                    definite_bucket_count = sum(
                        1
                        for other_b in range(len(rule.buckets))
                        if matrix[(c_idx, other_b)] == "DEFINITE"
                    )
                    if stage_mode == "EXCLUSIVE_DEFINITE" and definite_bucket_count > 1:
                        continue
                    if stage_mode == "SHARED_DEFINITE" and definite_bucket_count <= 1:
                        continue
                else:
                    if strength != "BORDERLINE":
                        continue

                if course.ects is None:
                    if c_idx not in used_uncredited_indices:
                        used_uncredited_indices.add(c_idx)
                        bucket_allocations[b_idx].append(
                            CountedCourse(
                                title=course.title,
                                ects=None,
                                allocated_ects=_ZERO,
                                strength="DEFINITE" if strength == "DEFINITE" else "BORDERLINE",
                                in_progress=course.in_progress,
                            )
                        )
                    continue

                avail = remaining_ects[c_idx]
                if avail <= _ZERO:
                    continue

                other_siblings_need = any(
                    other_b != b_idx
                    and matrix[(c_idx, other_b)] == "DEFINITE"
                    and (rule.buckets[other_b].min_ects or _ZERO)
                    > sum(
                        item.allocated_ects
                        for item in bucket_allocations[other_b]
                        if (course.in_progress or not item.in_progress)
                        and item.strength == "DEFINITE"
                    )
                    for other_b in range(len(rule.buckets))
                )
                current_def = sum(
                    item.allocated_ects
                    for item in bucket_allocations[b_idx]
                    if (course.in_progress or not item.in_progress)
                    and item.strength == "DEFINITE"
                )
                deficit_needed = max(_ZERO, (bucket.min_ects or _ZERO) - current_def)
                is_shared = stage_mode == "SHARED_DEFINITE" and other_siblings_need
                if is_shared and deficit_needed > _ZERO:
                    take = min(avail, deficit_needed)
                elif is_shared and deficit_needed == _ZERO:
                    continue
                else:
                    take = avail

                if take > _ZERO:
                    remaining_ects[c_idx] -= take
                    bucket_allocations[b_idx].append(
                        CountedCourse(
                            title=course.title,
                            ects=course.ects,
                            allocated_ects=take,
                            strength="DEFINITE" if strength == "DEFINITE" else "BORDERLINE",
                            in_progress=course.in_progress,
                        )
                    )

    bucket_evals: list[StatementEvaluation] = []
    all_counted: list[CountedCourse] = []

    for b_idx, bucket in enumerate(rule.buckets):
        allocated = bucket_allocations[b_idx]
        all_counted.extend(allocated)
        ev = _evaluate_single_bucket(bucket, allocated, courses)
        bucket_evals.append(ev)

    if rule.pool_min_ects is not None:
        combined_keys = tuple(
            dict.fromkeys(
                list(rule.pool_subject_keys)
                + [k for b in rule.buckets for k in b.subject_keys]
            )
        )
        pool_bucket = SubjectBucketRule(
            subject_label=rule.pool_subject_label or "combined subjects",
            subject_keys=combined_keys,
            min_ects=rule.pool_min_ects,
            allowed_deficit_ects=rule.allowed_deficit_ects,
        )
        pool_allocated: list[CountedCourse] = []
        for course in courses:
            st = classify_course_for_subject(course, combined_keys)
            if st in ("DEFINITE", "BORDERLINE"):
                pool_allocated.append(
                    CountedCourse(
                        title=course.title,
                        ects=course.ects,
                        allocated_ects=course.ects or _ZERO,
                        strength="DEFINITE" if st == "DEFINITE" else "BORDERLINE",
                        in_progress=course.in_progress,
                    )
                )
        pool_ev = _evaluate_single_bucket(pool_bucket, pool_allocated, courses)
        bucket_evals.insert(0, pool_ev)
        seen_titles = {c.title for c in all_counted}
        for pc in pool_allocated:
            if pc.title not in seen_titles:
                all_counted.append(pc)
                seen_titles.add(pc.title)

    if len(bucket_evals) == 1:
        return bucket_evals[0]

    outcomes = [ev.outcome for ev in bucket_evals]
    if "FAILED" in outcomes:
        overall: VerdictOutcome = "FAILED"
    elif "UNDECIDABLE" in outcomes:
        overall = "UNDECIDABLE"
    elif "CONDITIONAL_BRIDGE" in outcomes:
        overall = "CONDITIONAL_BRIDGE"
    elif "IN_PROGRESS" in outcomes:
        overall = "IN_PROGRESS"
    elif "BORDERLINE" in outcomes:
        overall = "BORDERLINE"
    else:
        overall = "SATISFIED"

    parts = [ev.status_text for ev in bucket_evals]
    comp_def_total = (
        bucket_evals[0].completed_definite_ects
        if rule.pool_min_ects is not None
        else sum((ev.completed_definite_ects for ev in bucket_evals), _ZERO)
    )
    comp_poss_total = (
        bucket_evals[0].completed_possible_ects
        if rule.pool_min_ects is not None
        else sum((ev.completed_possible_ects for ev in bucket_evals), _ZERO)
    )
    ip_total = (
        bucket_evals[0].in_progress_ects
        if rule.pool_min_ects is not None
        else sum((ev.in_progress_ects for ev in bucket_evals), _ZERO)
    )
    return StatementEvaluation(
        outcome=overall,
        status_text=" | ".join(parts),
        counted_courses=tuple(all_counted),
        completed_definite_ects=comp_def_total,
        completed_possible_ects=comp_poss_total,
        in_progress_ects=ip_total,
        required_ects=rule.pool_min_ects,
        missing_topics=tuple(t for ev in bucket_evals for t in ev.missing_topics),
    )


def _evaluate_single_bucket(
    bucket: SubjectBucketRule,
    allocated: list[CountedCourse],
    all_courses: tuple[NormalizedCourse, ...],
) -> StatementEvaluation:
    comp_def = [c for c in allocated if not c.in_progress and c.strength == "DEFINITE"]
    comp_bord = [c for c in allocated if not c.in_progress and c.strength == "BORDERLINE"]
    in_prog = [c for c in allocated if c.in_progress]
    uncredited = [c for c in allocated if c.ects is None]

    def_ects = sum((c.allocated_ects for c in comp_def), _ZERO)
    bord_ects = sum((c.allocated_ects for c in comp_bord), _ZERO)
    poss_ects = def_ects + bord_ects
    ip_ects = sum((c.allocated_ects for c in in_prog), _ZERO)

    missing_topics: list[str] = [
        topic
        for topic in bucket.required_topics
        if not any(course_matches_topic(c, topic) for c in all_courses)
    ]

    if bucket.min_courses is not None and bucket.min_ects is None:
        req_n = bucket.min_courses
        def_n = len(comp_def)
        poss_n = len(comp_def) + len(comp_bord)
        ip_n = len(in_prog)
        if def_n >= req_n and not missing_topics:
            outcome: VerdictOutcome = "SATISFIED"
            prefix = f"Met ({bucket.subject_label}) — counted {def_n} / {req_n} courses"
        elif def_n + ip_n >= req_n and not missing_topics:
            outcome = "IN_PROGRESS"
            prefix = (
                f"Conditional (in progress, {bucket.subject_label}) — counted "
                f"{def_n} / {req_n} completed + {ip_n} in progress"
            )
        elif poss_n >= req_n or (def_n >= req_n and missing_topics):
            outcome = "BORDERLINE"
            prefix = (
                f"Borderline ({bucket.subject_label}) — counted {def_n}–{poss_n} / {req_n} courses"
            )
        else:
            outcome = "FAILED"
            prefix = f"Not met ({bucket.subject_label}) — counted {def_n} / {req_n} courses"
        details = f"{prefix}: {_format_course_list(comp_def)}."
        if comp_bord:
            details += f" Borderline: {_format_course_list(comp_bord)}."
        if in_prog:
            details += f" In progress: {_format_course_list(in_prog)}."
        if missing_topics:
            details += f" Missing topics: {', '.join(missing_topics)}."
        return StatementEvaluation(
            outcome=outcome,
            status_text=details,
            counted_courses=tuple(allocated),
            missing_topics=tuple(missing_topics),
        )

    req_ects = bucket.min_ects or _ZERO
    label = bucket.subject_label

    if def_ects >= req_ects and not missing_topics:
        outcome = "SATISFIED"
        summary = (
            f"Met ({label}) — counted {_fmt_num(def_ects)} / {_fmt_num(req_ects)} ECTS: "
            f"{_format_course_list(comp_def)}."
        )
    elif def_ects >= req_ects and missing_topics:
        outcome = "BORDERLINE"
        summary = (
            f"Borderline ({label}) — counted {_fmt_num(def_ects)} / {_fmt_num(req_ects)} ECTS: "
            f"{_format_course_list(comp_def)}, but missing named topics: "
            f"{', '.join(missing_topics)}."
        )
    elif poss_ects >= req_ects:
        outcome = "BORDERLINE"
        summary = (
            f"Borderline ({label}) — counted {_fmt_num(def_ects)}–{_fmt_num(poss_ects)} of "
            f"{_fmt_num(req_ects)} ECTS: {_format_course_list(comp_def)}; "
            f"borderline: {_format_course_list(comp_bord)}."
        )
    elif def_ects + ip_ects >= req_ects or poss_ects + ip_ects >= req_ects:
        outcome = "IN_PROGRESS"
        summary = (
            f"Conditional (in progress, {label}) — counted {_fmt_num(def_ects)} / "
            f"{_fmt_num(req_ects)} ECTS completed: {_format_course_list(comp_def)} "
            f"+ {_fmt_num(ip_ects)} ECTS in progress: {_format_course_list(in_prog)}."
        )
        if comp_bord:
            summary += f" Borderline: {_format_course_list(comp_bord)}."
    elif uncredited and (def_ects + Decimal(len(uncredited) * 6)) >= req_ects:
        outcome = "UNDECIDABLE"
        summary = (
            f"Needs credit verification ({label}) — counted {_fmt_num(def_ects)} / "
            f"{_fmt_num(req_ects)} ECTS plus {len(uncredited)} course(s) without stated credits: "
            f"{_format_course_list(allocated)}."
        )
    elif (
        bucket.allowed_deficit_ects > _ZERO
        and (req_ects - poss_ects) <= bucket.allowed_deficit_ects
    ):
        deficit_amt = req_ects - def_ects
        outcome = "CONDITIONAL_BRIDGE"
        summary = (
            f"Conditional (bridging allowed, {label}) — counted {_fmt_num(def_ects)} / "
            f"{_fmt_num(req_ects)} ECTS ({_fmt_num(deficit_amt)} ECTS deficit within "
            f"{_fmt_num(bucket.allowed_deficit_ects)} ECTS make-up limit): "
            f"{_format_course_list(comp_def)}."
        )
    else:
        outcome = "FAILED"
        summary = (
            f"Not met ({label}) — counted {_fmt_num(def_ects)} / {_fmt_num(req_ects)} ECTS: "
            f"{_format_course_list(comp_def)}."
        )
        if comp_bord:
            summary += f" Borderline: {_format_course_list(comp_bord)}."
        if in_prog:
            summary += f" In progress: {_format_course_list(in_prog)}."
        total_transcript_ects = sum((c.ects or _ZERO for c in all_courses), _ZERO)
        if _ZERO < total_transcript_ects < Decimal("60"):
            summary += (
                f" (Note: only {_fmt_num(total_transcript_ects)} total ECTS are currently "
                "listed on your transcript — add your remaining courses if completed.)"
            )

    if missing_topics and outcome != "BORDERLINE":
        summary += f" Missing topics: {', '.join(missing_topics)}."

    return StatementEvaluation(
        outcome=outcome,
        status_text=summary,
        counted_courses=tuple(allocated),
        completed_definite_ects=def_ects,
        completed_possible_ects=poss_ects,
        in_progress_ects=ip_ects,
        required_ects=req_ects,
        missing_topics=tuple(missing_topics),
    )


# ---------------------------------------------------------------------------
# 5. Total Prior-Degree Credits, GPA, Language, GRE/GMAT & Experience Evaluator
# ---------------------------------------------------------------------------

_GPA_BAR_RE = re.compile(
    r"(?:minimum\s+(?:c?gpa|grade(?:\s+point\s+average)?|average(?:\s+grade|\s+mark)?)"
    r"(?:\s+of(?:\s+at\s+least)?)?|"
    r"c?gpa\s+of(?:\s+at\s+least)?|overall\s+(?:grade|average)\s+of|"
    r"grade\s+of\s+at\s+least)\s*:?\s*"
    r"(\d+(?:[.,]\d+)?)\s*(?:(%)|(?:/|out\s+of|on\s+a)\s*(\d+(?:[.,]\d+)?))?",
    re.IGNORECASE,
)

_GERMAN_GRADE_BAR_RE = re.compile(
    r"(?:german\s+grade|note|overall\s+grade|minimum\s+grade)\s*(?:of\s*)?"
    r"(\d[.,]\d)\s*(?:or\s+better|or\s+higher|oder\s+besser)",
    re.IGNORECASE,
)

_UK_HONOURS_BAR_RE = re.compile(
    r"\b(first-?class\s+honou?rs|1st\s+class(?:\s+honou?rs)?|"
    r"upper\s+second-?class(?:\s+honou?rs)?|2\s*[:.]\s*1(?:\s+honou?rs|\s+degree|\b)|"
    r"lower\s+second-?class(?:\s+honou?rs)?|2\s*[:.]\s*2(?:\s+honou?rs|\s+degree|\b))",
    re.IGNORECASE,
)

_LETTER_GRADE_BAR_RE = re.compile(
    r"(?:minimum\s+(?:c?gpa|grade(?:\s+point\s+average)?|average(?:\s+grade|\s+mark)?)"
    r"(?:\s+of(?:\s+at\s+least)?)?|"
    r"c?gpa\s+of(?:\s+at\s+least)?|overall\s+(?:grade|average)\s+of|"
    r"grade\s+of\s+at\s+least)\s*:?\s*"
    r"([ABC][+-]|[BC]\b|A(?=\s*(?:or\s+(?:better|higher|above|equivalent)|grade\b|average\b|"
    r"required\b|on\s+a\b|[\(\.,;]|$)))"
    r"\s*(?:\(\s*(\d[.,]\d+)\s*\))?",
    re.IGNORECASE,
)

_LETTER_GRADE_TO_GPA_4: dict[str, Decimal] = {
    "a+": Decimal("4.0"),
    "a": Decimal("4.0"),
    "a-": Decimal("3.7"),
    "b+": Decimal("3.3"),
    "b": Decimal("3.0"),
    "b-": Decimal("2.7"),
    "c+": Decimal("2.3"),
    "c": Decimal("2.0"),
    "c-": Decimal("1.7"),
    "d+": Decimal("1.3"),
    "d": Decimal("1.0"),
    "d-": Decimal("0.7"),
    "f": Decimal("0.0"),
}

_IELTS_BAR_RE = re.compile(r"\bielts\b[^0-9]{0,25}?(\d(?:[.,]\d)?)", re.IGNORECASE)
_IELTS_SUBSCORE_RE = re.compile(
    r"(?:no\s+(?:band|section|sub-?score|component)\s+(?:below|less\s+than|under)\s*"
    r"(\d{1,2}(?:[.,]\d)?)|"
    r"(?:at\s+least|minimum(?:\s+of)?|min\.?)\s+(\d{1,2}(?:[.,]\d)?)\s+in\s+"
    r"(?:each|all|every))",
    re.IGNORECASE,
)
_TOEFL_BAR_RE = re.compile(r"\btoefl(?:\s+ibt)?\b[^0-9]{0,25}?(\d{2,3})\b", re.IGNORECASE)
_PTE_BAR_RE = re.compile(r"\bpte(?:\s+academic)?\b[^0-9]{0,25}?(\d{2})\b", re.IGNORECASE)
_DUOLINGO_BAR_RE = re.compile(
    r"\b(?:duolingo(?:\s+english\s+test)?|det)\b[^0-9]{0,25}?(\d{2,3})\b",
    re.IGNORECASE,
)
_TESTDAF_BAR_RE = re.compile(
    r"\b(?:testdaf|tdn)\b[^0-9]{0,20}?(?:4\s*x\s*([345])|([345]|1[2-9]|20))\b",
    re.IGNORECASE,
)
_DSH_BAR_RE = re.compile(r"\bdsh\s*[-–]?\s*([123])\b", re.IGNORECASE)
_CEFR_BAR_RE = re.compile(
    r"\b(english|german|french|italian|spanish|dutch|russian|turkish|chinese|japanese|korean)"
    r"\b[^.]{0,35}?\b(A1|A2|B1|B2|C1|C2)\b"
    r"|\b(A1|A2|B1|B2|C1|C2)\b[^.]{0,25}?\b"
    r"(english|german|french|italian|spanish|dutch|russian|turkish|chinese|japanese|korean)\b",
    re.IGNORECASE,
)
_MOI_WAIVER_RE = re.compile(
    r"(?:medium\s+of\s+instruction|taught\s+(?:entirely\s+|exclusively\s+)?in\s+english|"
    r"degree\s+(?:completed\s+)?in\s+english|english-taught\s+(?:bachelor|degree))",
    re.IGNORECASE,
)
_GRE_QUANT_RE = re.compile(
    r"\bgre\b[^.]{0,40}?\b(?:quantitative|quant)\b[^0-9]{0,20}?(1[3-7]\d)\b",
    re.IGNORECASE,
)
_GMAT_BAR_RE = re.compile(r"\bgmat\b[^0-9]{0,25}?([4-8]\d0)\b", re.IGNORECASE)
_WORK_EXP_BAR_RE = re.compile(
    r"(?:at\s+least|minimum\s+of|min\.?\s*)\s*(\d{1,2})\s*(months?|years?)\s+of\s+"
    r"(?:(post-graduation|postgraduate)\s+)?(?:relevant\s+|full-time\s+|professional\s+)*"
    r"(?:work\s+|professional\s+)experience",
    re.IGNORECASE,
)
_GRADUATION_BY_DATE_RE = re.compile(
    r"(?:degree\s+(?:must\s+be\s+|is\s+)?(?:completed|awarded|obtained|conferred)|"
    r"graduat(?:ed|ion))\s+(?:by|no\s+later\s+than|before|on\s+or\s+before)\s+"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)
_GRADUATION_RECENCY_RE = re.compile(
    r"(?:graduated|degree\s+(?:must\s+have\s+been\s+)?(?:obtained|completed|awarded|conferred))"
    r"\s+(?:no\s+more\s+than|within(?:\s+the\s+last|\s+the\s+past)?)\s+(\d{1,2})\s+years?"
    r"(?:\s+(?:ago|prior|before))?",
    re.IGNORECASE,
)

_MONTH_NAMES: dict[str, int] = (
    {calendar.month_name[m].lower(): m for m in range(1, 13)}
    | {calendar.month_abbr[m].lower(): m for m in range(1, 13)}
    | {"sept": 9}
)


def is_coursework_or_credit_statement(text: str) -> bool:
    """Return True if `text` states a subject-pool credit/coursework rule or a total
    prior-degree ECTS floor (`180`/`210`/`240 ECTS`) that relies on transcript course rows."""
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return False
    return bool(
        parse_subject_pool_rule(cleaned) is not None
        or _TOTAL_DEGREE_CREDITS_RE.search(cleaned) is not None
    )


def is_scraper_competency_statement(text: str) -> bool:
    """Return True if `text` states an academic/competency admission requirement that
    `extract_tier0_programme_facts` should persist as a `COMPETENCY` `ProgramStatement`."""
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return False
    return bool(
        is_coursework_or_credit_statement(cleaned)
        or _GERMAN_GRADE_BAR_RE.search(cleaned) is not None
        or _UK_HONOURS_BAR_RE.search(cleaned) is not None
        or _GPA_BAR_RE.search(cleaned) is not None
        or _LETTER_GRADE_BAR_RE.search(cleaned) is not None
        or _WORK_EXP_BAR_RE.search(cleaned) is not None
        or _GRADUATION_BY_DATE_RE.search(cleaned) is not None
        or _GRADUATION_RECENCY_RE.search(cleaned) is not None
    )


_DATE_STAMP_STRIP_RE = re.compile(
    r"\b\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)\d{2}\b"
    r"|\b(?:19|20)\d{2}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(?:19|20)\d{2}\b",
    re.IGNORECASE,
)

_INTAKE_OPEN_ENDED_EXTRACT_RE = re.compile(
    r"\b((?:from|since|after)\s+(?:the\s+)?(?:19|20)\d{2}(?:[-/](?:\d{2}|\d{4}))?"
    r"(?:\s+(?:student\s+)?(?:intake|cohort|edition|academic\s+year))?(?:\s+onwards)?)\b"
    r"|\b((?:19|20)\d{2}(?:[-/](?:\d{2}|\d{4}))?(?:\s+(?:student\s+)?intake)?\s+onwards)\b",
    re.IGNORECASE,
)

_INTAKE_MULTI_EXTRACT_RE = re.compile(
    r"\b((?:19|20)\d{2}(?:[-/](?:\d{2}|\d{4}))?"
    r"(?:\s*(?:,|;|&|\band\b|\bor\b)\s*(?:19|20)\d{2}(?:[-/](?:\d{2}|\d{4}))?)+)\b",
    re.IGNORECASE,
)

_INTAKE_COHORT_RANGE_EXTRACT_RE = re.compile(
    r"\b((?:19|20)\d{2}\s*[-/]\s*(?:(?:19|20)?\d{2}))\b"
)

_INTAKE_SINGLE_YEAR_EXTRACT_RE = re.compile(
    r"\b(?:(?:fall|autumn|spring|winter|summer|intake|cohort|edition|academic\s+year|"
    r"recruitment|admission|call)\s+(?:of\s+|for\s+)?((?:19|20)\d{2})"
    r"|((?:19|20)\d{2})\s+(?:student\s+)?(?:intake|cohort|edition|academic\s+year|"
    r"recruitment|admission|call))\b",
    re.IGNORECASE,
)

_SCHOLARSHIP_PENDING_RENEWAL_RE = re.compile(
    r"(?:scholarships?|funding|grants?)\s+[^.;]{0,90}?\b(?:subject\s+to|pending|"
    r"conditional\s+(?:on|upon)|awaiting)\s+[^.;]{0,70}?\b(?:eacea|eu\s+grant|erasmus|"
    r"grant\s+renewal|re-?accreditation|funding\s+approval|selection\s+by\s+eacea)\b"
    r"|\b(?:pending|subject\s+to|awaiting)\s+(?:the\s+)?(?:renewal|approval|selection|"
    r"continuation)\s+of\s+(?:the\s+)?(?:erasmus|eacea|eu)\s+(?:mundus\s+)?(?:grant|funding|project)\b",
    re.IGNORECASE,
)

_NO_SCHOLARSHIP_STATEMENT_RE = re.compile(
    r"\bwithout\s+(?:any\s+)?(?:erasmus(?:\s+mundus)?\s+|consortium\s+)?scholarships?\b"
    r"|\bno\s+(?:erasmus(?:\s+mundus)?\s+|consortium\s+|emjm\s+)?scholarships?\s+"
    r"(?:for\s+[^.;]{0,40}?\s+)?(?:are|will\s+be|is)\s+"
    r"(?:offered|available|awarded|granted|provided)\b"
    r"|\b(?:recruitment|admission|applications?|call)\s+(?:[^.;]{0,60}?\s+)?"
    r"(?:is|are|will\s+be)\s+(?:open\s+)?(?:for|to)\s+self[- ](?:funded|paying|financing)\s+"
    r"(?:students|applicants|candidates)\s+only\b"
    r"|\bonly\s+self[- ](?:funded|paying|financing)\s+(?:students|applicants|candidates)\s+"
    r"(?:will\s+be|are|can\s+be)\s+(?:admitted|recruited|accepted|considered)\b"
    r"|\bscholarship\s+applications?\s+(?:for\s+[^.;]{0,50}?\s+)?(?:are|is)\s+(?:now\s+)?closed\b"
    r"|\b(?:erasmus(?:\s+mundus)?|eacea|eu)\s+(?:grant|funding)\s+(?:period\s+)?"
    r"(?:has\s+)?(?:ended|expired)\b",
    re.IGNORECASE,
)

_PARTIAL_WAIVER_EXCEPTION_RE = re.compile(
    r"\b(?:however|but|although|though)\b[^.;]{0,90}?\b(?:tuition\s+waivers?|fee\s+waivers?|"
    r"partial\s+scholarships?|consortium\s+(?:scholarships?|waivers?|grants?))\s+"
    r"(?:are|will\s+be|is)\s+(?:still\s+)?(?:offered|available|awarded|granted)\b",
    re.IGNORECASE,
)


def _extract_scholarship_statement_intake(text: str) -> str:
    stripped = _DATE_STAMP_STRIP_RE.sub(" ", text)
    m_open = _INTAKE_OPEN_ENDED_EXTRACT_RE.search(stripped)
    if m_open:
        return (m_open.group(1) or m_open.group(2) or "").strip()
    m_multi = _INTAKE_MULTI_EXTRACT_RE.search(stripped)
    if m_multi:
        return m_multi.group(1).strip()
    m_range = _INTAKE_COHORT_RANGE_EXTRACT_RE.search(stripped)
    if m_range:
        return m_range.group(1).replace(" ", "")
    m_single = _INTAKE_SINGLE_YEAR_EXTRACT_RE.search(stripped)
    if m_single:
        return (m_single.group(1) or m_single.group(2) or "").strip()
    return "UNSTATED"


ScholarshipStatusKind = Literal["NO_SCHOLARSHIP", "NO_FULL_SCHOLARSHIP", "PENDING_RENEWAL"]


def parse_scholarship_status_statement(
    text: str,
) -> tuple[ScholarshipStatusKind, str] | None:
    """Detect deterministic scholarship-suspension, self-funded-only, or pending-grant-renewal
    disclaimers on a programme page and return `(status_kind, applies_to)`."""
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return None
    if _NO_SCHOLARSHIP_STATEMENT_RE.search(cleaned):
        applies_to = _extract_scholarship_statement_intake(cleaned)
        if _PARTIAL_WAIVER_EXCEPTION_RE.search(cleaned):
            return ("NO_FULL_SCHOLARSHIP", applies_to)
        return ("NO_SCHOLARSHIP", applies_to)
    if _SCHOLARSHIP_PENDING_RENEWAL_RE.search(cleaned):
        applies_to = _extract_scholarship_statement_intake(cleaned)
        return ("PENDING_RENEWAL", applies_to)
    return None


def is_program_scholarship_suspended_for_intake(
    statement_text: str,
    target_intake_year: int | str | None,
    *,
    money_form: str = "GRANT",
) -> bool:
    """Return True when `statement_text` states that scholarships (or full grants) are not
    available for `target_intake_year`."""
    from apps.funding.validity import intake_matches_target

    parsed = parse_scholarship_status_statement(statement_text)
    if parsed is None:
        return False
    status_kind, applies_to = parsed
    if status_kind == "PENDING_RENEWAL":
        return False
    if not intake_matches_target(applies_to, target_intake_year):
        return False
    if status_kind == "NO_FULL_SCHOLARSHIP" and money_form == "FEE_WAIVER":
        return False
    return True


_ERASMUS_PROGRAMME_COUNTRIES: frozenset[str] = frozenset(
    {
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU",
        "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MK", "MT", "NL", "NO", "PL", "PT", "RO",
        "RS", "SE", "SI", "SK", "TR",
    }
)

_EU_EEA_CH_COUNTRIES: frozenset[str] = frozenset(REGIONS["EEA"].countries) | {"CH"}

_ERASMUS_12_MONTH_RULE_RE = re.compile(
    r"\b(?:12[- ]month\s+rule|more\s+than\s+(?:a\s+total\s+of\s+)?12\s+months?\s+over\s+the\s+"
    r"last\s+5\s+years|resided\s+or\s+carried\s+out\s+their\s+main\s+activity[^.;]{0,80}?"
    r"12\s+months)\b",
    re.IGNORECASE,
)

_DATE_TEXT_PATTERN = (
    r"(?:(?:19|20)\d{2}-\d{2}-\d{2}"
    r"|\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*,?\s+(?:19|20)\d{2}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+(?:19|20)\d{2})"
)

_NON_EU_VISA_DEADLINE_RE = re.compile(
    rf"\b(?:non[- ]eu(?:/eea)?|international|partner[- ]country|visa[- ]requir\w+|"
    rf"requiring\s+a\s+(?:study\s+)?visa)[^.;]{{0,70}}?\b(?:by|until|before|on|deadline[:\s]+)\s*"
    rf"({_DATE_TEXT_PATTERN})",
    re.IGNORECASE,
)

_EU_DOMESTIC_DEADLINE_RE = re.compile(
    rf"(?<![-a-z])\b(?:eu(?:/eea)?|eea|programme[- ]country|domestic|visa[- ]exempt)[^.;]{{0,70}}?"
    rf"\b(?:by|until|before|on|deadline[:\s]+)\s*({_DATE_TEXT_PATTERN})",
    re.IGNORECASE,
)


def _parse_iso_or_human_date(raw: str) -> _date | None:
    cleaned = " ".join(raw.strip().replace(",", "").split())
    try:
        return _date.fromisoformat(cleaned)
    except ValueError:
        pass
    parts = cleaned.split()
    if len(parts) == 3:
        if parts[0].isdigit() and parts[2].isdigit():
            m = _MONTH_NAMES.get(parts[1].casefold())
            if m is not None:
                try:
                    return _date(int(parts[2]), m, int(parts[0]))
                except ValueError:
                    return None
        if parts[1].isdigit() and parts[2].isdigit():
            m = _MONTH_NAMES.get(parts[0].casefold())
            if m is not None:
                try:
                    return _date(int(parts[2]), m, int(parts[1]))
                except ValueError:
                    return None
    return None


def convert_to_german_bavarian_grade(
    grade: Decimal,
    max_grade: Decimal,
    min_passing_grade: Decimal,
) -> Decimal | None:
    """Modified Bavarian Formula (`Modifizierte Bayerische Formel`):
    `1 + 3 * (N_max - N_student) / (N_max - N_min)`, clamped to `[1.0, 5.0]`."""
    if max_grade <= min_passing_grade or grade > max_grade:
        return None
    if grade < min_passing_grade:
        return Decimal("5.0")
    raw = Decimal("1") + Decimal("3") * (max_grade - grade) / (max_grade - min_passing_grade)
    return raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


_STATUTORY_SCALE_BOUNDS: dict[Decimal, tuple[Decimal, Decimal]] = {
    Decimal("4"): (Decimal("4.0"), Decimal("2.0")),
    Decimal("4.3"): (Decimal("4.3"), Decimal("2.0")),
    Decimal("4.5"): (Decimal("4.5"), Decimal("2.0")),
    Decimal("5"): (Decimal("5.0"), Decimal("3.0")),
    Decimal("6"): (Decimal("6.0"), Decimal("4.0")),
    Decimal("7"): (Decimal("7.0"), Decimal("4.0")),
    Decimal("10"): (Decimal("10.0"), Decimal("5.0")),
    Decimal("20"): (Decimal("20.0"), Decimal("10.0")),
    Decimal("30"): (Decimal("30.0"), Decimal("18.0")),
    Decimal("100"): (Decimal("100.0"), Decimal("50.0")),
    Decimal("110"): (Decimal("110.0"), Decimal("66.0")),
}


def _extract_scale_max(scale_str: str) -> Decimal | None:
    """Extract the numeric scale ceiling (`4.0`, `100`, `20`, etc.) from `scale_str`,
    handling range strings (`0-100`, `1-100`, `18-30`) and prose (`out of 100`, `GPA 4.0`)."""
    s = " ".join(scale_str.strip().split()).casefold()
    if not s:
        return None
    m_range = re.search(
        r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)(?![\d.,])", s
    )
    if m_range:
        low = _parse_decimal(m_range.group(1))
        high = _parse_decimal(m_range.group(2))
        if low is not None and high is not None and high > low:
            return high
    if any(tok in s for tok in ("percentage", "percent")):
        return Decimal("100")
    cleaned = (
        re.sub(
            r"\b(?:cgpa|gpa|out\s+of|on\s+a|scale|point|points|grade)\b",
            " ",
            s,
        )
        .replace("%", "")
        .replace("/", " ")
        .strip()
    )
    if "%" in s and not cleaned:
        return Decimal("100")
    direct = _parse_decimal(cleaned)
    if direct is not None:
        return direct
    nums = [n for tok in re.findall(r"\d+(?:[.,]\d+)?", cleaned) if (n := _parse_decimal(tok))]
    return nums[-1] if nums else None


def _parse_scale_bounds(
    scale_str: str,
    country_code: str = "",
) -> tuple[Decimal, Decimal, bool] | None:
    """Return `(max_grade, min_passing_grade, has_explicit_min)` for an ascending grading scale."""
    if _is_german_inverted_scale(scale_str, country_code):
        return None
    s = " ".join(scale_str.strip().split()).casefold()
    cc = country_code.strip().upper()
    explicit_low: Decimal | None = None
    scale_num: Decimal | None = None

    m_range = re.search(
        r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)(?![\d.,])", s
    )
    if m_range:
        low = _parse_decimal(m_range.group(1))
        high = _parse_decimal(m_range.group(2))
        if low is not None and high is not None and high > low:
            scale_num = high
            if low > Decimal("1"):
                explicit_low = low
    if scale_num is None:
        scale_num = _extract_scale_max(scale_str)
    if scale_num is None:
        return None
    bounds = _STATUTORY_SCALE_BOUNDS.get(scale_num)
    if bounds is None:
        return None
    if explicit_low is not None:
        return (bounds[0], explicit_low, True)
    max_g, min_pass = bounds
    if max_g == Decimal("100"):
        if cc == "CN":
            min_pass = Decimal("60.0")
        elif cc == "AZ":
            min_pass = Decimal("51.0")
    return (max_g, min_pass, False)


def _parse_record_grade_and_scale(
    grade_str: str,
    scale_str: str,
) -> tuple[Decimal | None, str]:
    """Parse `AcademicRecord.grade` and `grading_scale`, supporting composite strings
    (`88/100`, `16.45/20.0 (Highest Honors)`, `1.7 (gut)`, `First Class (74%)`) and
    letter grades (`A`, `A-`, `B+`, `B`, `B-`, `C+`, `C`)."""
    g_raw = " ".join(grade_str.strip().split())
    s_raw = " ".join(scale_str.strip().split())
    if not g_raw:
        return None, s_raw

    direct = _parse_decimal(g_raw)
    if direct is not None:
        if g_raw.endswith("%") and not s_raw:
            return direct, "100"
        return direct, s_raw

    m_slash = re.match(
        r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)\b",
        g_raw,
    )
    if m_slash:
        g_val = _parse_decimal(m_slash.group(1))
        denom = m_slash.group(2)
        eff_s = s_raw if (s_raw and _extract_scale_max(s_raw) is not None) else denom
        return g_val, eff_s

    m_lead = re.match(
        r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*(%)?(?:\s*[\(\[\-–—]|\s+[a-zA-Z])",
        g_raw,
    )
    if m_lead and _uk_honours_tier(g_raw) is None:
        g_val = _parse_decimal(m_lead.group(1))
        eff_s = s_raw or ("100" if m_lead.group(2) else "")
        return g_val, eff_s

    m_pct_in_parens = re.search(r"\(\s*(\d+(?:[.,]\d+)?)\s*%\s*\)", g_raw)
    if m_pct_in_parens:
        g_val = _parse_decimal(m_pct_in_parens.group(1))
        eff_s = s_raw if (s_raw and _extract_scale_max(s_raw) is not None) else "100"
        return g_val, eff_s

    m_letter = re.match(
        r"^\s*([abcdf][+-]?)(?:\s*$|(?:\s*[\(\[\-–—].*)|\s+grade\b)",
        g_raw,
        re.IGNORECASE,
    )
    if m_letter:
        tok = m_letter.group(1).casefold()
        if tok in _LETTER_GRADE_TO_GPA_4:
            return _LETTER_GRADE_TO_GPA_4[tok], "4.0"

    return None, s_raw


_UNSTATED_MARKERS: frozenset[str] = frozenset(
    {"", "not stated", "unknown", "n/a", "na", "none", "-", "—"}
)


def _infer_unstated_scale(
    grade_val: Decimal | None,
    country_code: str,
    *,
    courses: tuple[object, ...] = (),
) -> str:
    cc = country_code.strip().upper()
    course_nums: list[Decimal] = []
    for c in courses:
        cg_raw = getattr(c, "grade", None)
        cg_str = str(cg_raw).strip() if cg_raw is not None else ""
        if not cg_str:
            continue
        cg_val, cg_scale = _parse_record_grade_and_scale(cg_str, "")
        if cg_scale and cg_scale.casefold() not in _UNSTATED_MARKERS:
            return cg_scale
        if cg_val is not None:
            course_nums.append(cg_val)

    probe = grade_val if grade_val is not None else (max(course_nums) if course_nums else None)
    if probe is None:
        return ""
    if cc == "IT" and Decimal("66") <= probe <= Decimal("110"):
        return "110"
    if Decimal("50") <= probe <= Decimal("100"):
        return "100"
    if cc == "IT" and Decimal("18") <= probe <= Decimal("30"):
        return "30"
    if Decimal("10") < probe <= Decimal("20") or (
        probe == Decimal("10")
        and cc in {"FR", "BE", "PT", "IR", "MA", "TN", "DZ", "GR", "PE", "VE"}
    ):
        return "20"
    if cc == "CH" and Decimal("4.0") < probe <= Decimal("6.0"):
        return "1.0-6.0"
    if Decimal("5.0") < probe <= Decimal("10.0"):
        return "10.0"
    if Decimal("4.0") < probe <= Decimal("5.0"):
        return "5.0"
    if Decimal("0.7") <= probe <= Decimal("4.0"):
        if cc in {"DE", "AT"}:
            return "1.0-5.0"
        if cc not in {"CH", "RU", "BY"}:
            return "4.0"
    return ""


def _resolve_record_grade_and_scale(
    rec: object,
) -> tuple[Decimal | None, str, str]:
    """Resolve `(grade_val, effective_scale_str, custom_display_label)` for an `AcademicRecord`,
    inferring the scale when `grading_scale` is `'not stated'` and falling back to the
    ECTS-weighted average of completed passing transcript courses when `grade` is `'not stated'`."""
    raw_grade_str = str(getattr(rec, "grade", "") or "").strip()
    raw_scale_str = str(getattr(rec, "grading_scale", "") or "").strip()
    cc = str(getattr(rec, "country_code", "") or "").strip().upper()
    raw_courses = tuple(getattr(rec, "courses", ()) or ())

    g_val, eff_scale = _parse_record_grade_and_scale(raw_grade_str, raw_scale_str)
    if eff_scale.casefold() in _UNSTATED_MARKERS:
        eff_scale = _infer_unstated_scale(g_val, cc, courses=raw_courses)

    if g_val is not None:
        return g_val, eff_scale, ""

    if raw_grade_str.casefold() in _UNSTATED_MARKERS:
        weighted_sum = _ZERO
        total_weight = _ZERO
        unweighted_vals: list[Decimal] = []
        inferred_course_scale = eff_scale
        course_count = 0
        for c in raw_courses:
            if bool(getattr(c, "in_progress", False)):
                continue
            cg_raw = getattr(c, "grade", None)
            cg_str = str(cg_raw).strip() if cg_raw is not None else ""
            if not cg_str or is_failing_or_withdrawn_grade(cg_str, eff_scale, cc):
                continue
            cg_val, cg_scale = _parse_record_grade_and_scale(cg_str, eff_scale)
            if cg_val is None:
                continue
            if not inferred_course_scale and cg_scale.casefold() not in _UNSTATED_MARKERS:
                inferred_course_scale = cg_scale
            course_count += 1
            unweighted_vals.append(cg_val)
            raw_ects = getattr(c, "ects", None)
            c_ects = (
                raw_ects
                if isinstance(raw_ects, Decimal)
                else _parse_decimal(str(raw_ects))
                if raw_ects is not None
                else None
            )
            if c_ects is not None and c_ects > _ZERO:
                weighted_sum += cg_val * c_ects
                total_weight += c_ects
        if course_count > 0:
            raw_avg = (
                weighted_sum / total_weight
                if total_weight > _ZERO
                else sum(unweighted_vals, _ZERO) / Decimal(course_count)
            )
            avg_val = raw_avg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if avg_val == avg_val.to_integral_value():
                avg_val = avg_val.quantize(Decimal("0.1"))
            if not inferred_course_scale:
                inferred_course_scale = _infer_unstated_scale(avg_val, cc)
            lbl = (
                f"transcript course average {_fmt_num(avg_val)}/{inferred_course_scale} "
                f"({course_count} courses)"
            )
            return avg_val, inferred_course_scale, lbl

    return None, eff_scale, ""


def _uk_honours_tier(raw: str) -> tuple[int, str] | None:
    cf = " ".join(raw.strip().split()).casefold()
    if re.search(r"\b(?:first-?class|1st(?:\s+class)?)\b", cf):
        return 3, "First-Class Honours (1st)"
    if re.search(r"\b(?:upper\s+second-?class|2\s*[:.]\s*1)\b", cf):
        return 2, "Upper Second-Class Honours (2:1)"
    if re.search(r"\b(?:lower\s+second-?class|2\s*[:.]\s*2)\b", cf):
        return 1, "Lower Second-Class Honours (2:2)"
    return None


def _bavarian_from_record(
    grade_val: Decimal | None,
    scale_str: str,
    *,
    country_code: str = "",
    raw_grade_str: str = "",
) -> Decimal | None:
    cc = country_code.strip().upper()
    if grade_val is not None and _is_german_inverted_scale(scale_str, cc):
        if Decimal("0.7") <= grade_val <= Decimal("5.0"):
            return max(Decimal("1.0"), grade_val).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return None

    if grade_val is None:
        hon = _uk_honours_tier(raw_grade_str) or _uk_honours_tier(scale_str)
        if hon is not None:
            return {3: Decimal("1.3"), 2: Decimal("2.0"), 1: Decimal("2.7")}[hon[0]]
        return None

    parsed_bounds = _parse_scale_bounds(scale_str, cc)
    if parsed_bounds is None:
        hon = _uk_honours_tier(raw_grade_str) or _uk_honours_tier(scale_str)
        if hon is not None:
            return {3: Decimal("1.3"), 2: Decimal("2.0"), 1: Decimal("2.7")}[hon[0]]
        return None

    max_g, min_pass, has_explicit_min = parsed_bounds
    if not has_explicit_min:
        if max_g == Decimal("100") and cc in {"GB", "UK", "IE", "AU", "NZ"}:
            if grade_val > Decimal("100") or grade_val < _ZERO:
                return None
            if grade_val >= Decimal("70"):
                raw = (
                    Decimal("1.0")
                    + Decimal("0.5") * (Decimal("100") - grade_val) / Decimal("30")
                )
            elif grade_val >= Decimal("60"):
                raw = (
                    Decimal("1.6")
                    + Decimal("0.7") * (Decimal("70") - grade_val) / Decimal("10")
                )
            elif grade_val >= Decimal("50"):
                raw = (
                    Decimal("2.4")
                    + Decimal("0.6") * (Decimal("60") - grade_val) / Decimal("10")
                )
            elif grade_val >= Decimal("40"):
                raw = (
                    Decimal("3.1")
                    + Decimal("0.9") * (Decimal("50") - grade_val) / Decimal("10")
                )
            else:
                return Decimal("5.0")
            return raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if max_g == Decimal("10") and cc == "NL":
            if grade_val > Decimal("10") or grade_val < _ZERO:
                return None
            return convert_to_german_bavarian_grade(
                min(grade_val, Decimal("8.5")),
                Decimal("8.5"),
                Decimal("5.5"),
            )

    return convert_to_german_bavarian_grade(grade_val, max_g, min_pass)


def convert_grade_to_bavarian(
    grade: str | Decimal,
    grading_scale: str = "",
    country_code: str = "",
) -> Decimal | None:
    """Convert any supported numeric, composite, letter, German/Austrian inverted, or
    UK Honours grade into its German Modified Bavarian (`1.0` best – `5.0` fail) equivalent."""
    raw_g = str(grade).strip()
    g_val, eff_scale = _parse_record_grade_and_scale(raw_g, grading_scale)
    if eff_scale.casefold() in _UNSTATED_MARKERS:
        eff_scale = _infer_unstated_scale(g_val, country_code)
    return _bavarian_from_record(
        g_val,
        eff_scale,
        country_code=country_code,
        raw_grade_str=raw_g,
    )


def convert_bavarian_to_us_gpa(bavarian_grade: Decimal) -> Decimal:
    """Invert the Modified Bavarian Formula onto the standard US `4.0` GPA scale
    (`1.0 -> 4.00`, `2.5 -> 3.00`, `4.0 -> 2.00`, `> 4.0 -> 0.00`)."""
    if bavarian_grade <= Decimal("1.0"):
        return Decimal("4.00")
    if bavarian_grade > Decimal("4.0"):
        return Decimal("0.00")
    raw = Decimal("4.0") - (bavarian_grade - Decimal("1.0")) * Decimal("2.0") / Decimal("3.0")
    return raw.quantize(_CENT, rounding=ROUND_HALF_UP)


def _evaluate_uk_honours_for_record(
    req_tier: int,
    req_label: str,
    rec: object,
) -> StatementEvaluation | None:
    grade_str = str(getattr(rec, "grade", "") or "").strip()
    scale_str = str(getattr(rec, "grading_scale", "") or "").strip()
    country_code = str(getattr(rec, "country_code", "") or "").upper()

    held_hon = _uk_honours_tier(grade_str) or _uk_honours_tier(scale_str)
    if held_hon is not None:
        sat = held_hon[0] >= req_tier
        return StatementEvaluation(
            outcome="SATISFIED" if sat else "FAILED",
            status_text=(
                f"{'Met' if sat else 'Not met'} — counted {held_hon[1]} against "
                f"required {req_label}."
            ),
        )

    grade_val, eff_scale_str, custom_lbl = _resolve_record_grade_and_scale(rec)
    if grade_val is None:
        return None

    if _is_german_inverted_scale(eff_scale_str, country_code):
        de_bar = {3: Decimal("1.5"), 2: Decimal("2.3"), 1: Decimal("3.0")}[req_tier]
        sat = grade_val <= de_bar
        de_lbl = custom_lbl or f"German grade {grade_val}"
        return StatementEvaluation(
            outcome="SATISFIED" if sat else "FAILED",
            status_text=(
                f"{'Met' if sat else 'Not met'} — counted {de_lbl} "
                f"against {req_label} (≈ {de_bar} or better)."
            ),
        )

    scale_num = _extract_scale_max(eff_scale_str)
    if scale_num == Decimal("100") and country_code in {"GB", "UK", "IE", "AU", "NZ"}:
        uk_pct_bar = {3: Decimal("70"), 2: Decimal("60"), 1: Decimal("50")}[req_tier]
        sat = grade_val >= uk_pct_bar
        return StatementEvaluation(
            outcome="SATISFIED" if sat else "FAILED",
            status_text=(
                f"{'Met' if sat else 'Not met'} — counted "
                f"{custom_lbl or f'{grade_val}% ({country_code})'} "
                f"against {req_label} (>= {int(uk_pct_bar)}%)."
            ),
        )

    bav = _bavarian_from_record(
        grade_val,
        eff_scale_str,
        country_code=country_code,
        raw_grade_str=grade_str,
    )
    if bav is not None:
        de_bar = {3: Decimal("1.5"), 2: Decimal("2.3"), 1: Decimal("3.0")}[req_tier]
        sat = bav <= de_bar
        return StatementEvaluation(
            outcome="SATISFIED" if sat else "FAILED",
            status_text=(
                f"{'Met' if sat else 'Not met'} — counted "
                f"{custom_lbl or f'grade {grade_val}/{eff_scale_str}'} "
                f"(≈ {bav} Bavarian grade) against {req_label}."
            ),
        )
    return None


def _evaluate_total_degree_credits(
    required_ects: Decimal,
    profile: object,
) -> StatementEvaluation:
    courses = normalize_transcript_courses(profile)
    if not courses:
        return StatementEvaluation(
            outcome="UNDECIDABLE",
            status_text=(
                f"Not yet checked against {int(required_ects)} ECTS degree requirement — "
                "no transcript courses on your profile."
            ),
            required_ects=required_ects,
        )
    comp_ects = sum((c.ects or _ZERO for c in courses if not c.in_progress), _ZERO)
    ip_ects = sum((c.ects or _ZERO for c in courses if c.in_progress), _ZERO)
    comp_count = sum(1 for c in courses if not c.in_progress and c.ects is not None)
    ip_count = sum(1 for c in courses if c.in_progress and c.ects is not None)

    if comp_ects >= required_ects:
        return StatementEvaluation(
            outcome="SATISFIED",
            status_text=(
                f"Met — counted {_fmt_num(comp_ects)} / {_fmt_num(required_ects)} total ECTS "
                f"completed across {comp_count} transcript courses."
            ),
            completed_definite_ects=comp_ects,
            completed_possible_ects=comp_ects,
            in_progress_ects=ip_ects,
            required_ects=required_ects,
        )
    if comp_ects + ip_ects >= required_ects:
        return StatementEvaluation(
            outcome="IN_PROGRESS",
            status_text=(
                f"Conditional (in progress) — counted {_fmt_num(comp_ects)} / "
                f"{_fmt_num(required_ects)} total ECTS completed ({comp_count} courses) + "
                f"{_fmt_num(ip_ects)} ECTS in progress ({ip_count} courses)."
            ),
            completed_definite_ects=comp_ects,
            completed_possible_ects=comp_ects,
            in_progress_ects=ip_ects,
            required_ects=required_ects,
        )
    return StatementEvaluation(
        outcome="FAILED",
        status_text=(
            f"Not met — counted {_fmt_num(comp_ects)} / {_fmt_num(required_ects)} total ECTS "
            f"across {comp_count} completed courses"
            + (f" (+ {_fmt_num(ip_ects)} ECTS in progress)." if ip_ects > _ZERO else ".")
        ),
        completed_definite_ects=comp_ects,
        completed_possible_ects=comp_ects,
        in_progress_ects=ip_ects,
        required_ects=required_ects,
    )


def _evaluate_grade_or_gpa_statement(text: str, profile: object) -> StatementEvaluation | None:
    records = tuple(getattr(profile, "academic_history", ()) or ())
    if not records:
        return None

    m_de_grade = _GERMAN_GRADE_BAR_RE.search(text)
    if m_de_grade:
        bar_de = _parse_decimal(m_de_grade.group(1))
        if bar_de is not None:
            de_evals: list[StatementEvaluation] = []
            for rec in records:
                raw_grade_str = str(getattr(rec, "grade", "") or "").strip()
                country_code = str(getattr(rec, "country_code", "") or "").strip().upper()
                grade_val, scale_str, custom_lbl = _resolve_record_grade_and_scale(rec)
                if grade_val is not None and _is_german_inverted_scale(scale_str, country_code):
                    sat = grade_val <= bar_de
                    de_scale_lbl = scale_str or "German scale"
                    de_counted_lbl = custom_lbl or f"grade {grade_val} on {de_scale_lbl}"
                    de_evals.append(
                        StatementEvaluation(
                            outcome="SATISFIED" if sat else "FAILED",
                            status_text=(
                                f"{'Met' if sat else 'Not met'} — counted {de_counted_lbl} "
                                f"against required {bar_de} or better."
                            ),
                        )
                    )
                    continue
                bav = _bavarian_from_record(
                    grade_val,
                    scale_str,
                    country_code=country_code,
                    raw_grade_str=raw_grade_str,
                )
                if bav is not None:
                    held_lbl = custom_lbl or (
                        f"{grade_val}/{scale_str}"
                        if grade_val is not None and scale_str
                        else (raw_grade_str or scale_str)
                    )
                    held_disp = held_lbl if custom_lbl else f"grade {held_lbl}"
                    if bav <= bar_de - Decimal("0.2"):
                        de_evals.append(
                            StatementEvaluation(
                                outcome="SATISFIED",
                                status_text=(
                                    f"Met — counted {held_disp} "
                                    f"(≈ {bav} Bavarian grade) against {bar_de} or better."
                                ),
                            )
                        )
                    elif bav <= bar_de + Decimal("0.2"):
                        de_evals.append(
                            StatementEvaluation(
                                outcome="BORDERLINE",
                                status_text=(
                                    f"Borderline — counted "
                                    f"{held_lbl if custom_lbl else f'grade {held_lbl}'} "
                                    f"(≈ {bav} Bavarian grade, depending on minimum passing mark) "
                                    f"against {bar_de}."
                                ),
                            )
                        )
                    else:
                        de_evals.append(
                            StatementEvaluation(
                                outcome="FAILED",
                                status_text=(
                                    f"Not met — counted "
                                    f"{held_lbl if custom_lbl else f'grade {held_lbl}'} "
                                    f"(≈ {bav} Bavarian grade) against {bar_de} or better."
                                ),
                            )
                        )
            if de_evals:
                return max(de_evals, key=lambda e: _OUTCOME_RANK.get(e.outcome, 0))

    m_uk = _UK_HONOURS_BAR_RE.search(text)
    if m_uk:
        hon = _uk_honours_tier(m_uk.group(1))
        if hon is not None:
            uk_evals = [
                ev
                for rec in records
                if (ev := _evaluate_uk_honours_for_record(hon[0], hon[1], rec)) is not None
            ]
            if uk_evals:
                return max(uk_evals, key=lambda e: _OUTCOME_RANK.get(e.outcome, 0))

    bar_val: Decimal | None = None
    scale_val: Decimal | None = None
    m_gpa = _GPA_BAR_RE.search(text)
    if m_gpa:
        bar_val = _parse_decimal(m_gpa.group(1))
        pct_tok = m_gpa.group(2)
        scale_val = _parse_decimal(m_gpa.group(3)) if m_gpa.group(3) else None
        if bar_val is not None:
            if pct_tok:
                scale_val = Decimal("100")
            elif scale_val is None and bar_val <= Decimal("4.0"):
                scale_val = Decimal("4.0")
            elif scale_val is None and bar_val >= Decimal("50"):
                scale_val = Decimal("100")
    else:
        m_letter_bar = _LETTER_GRADE_BAR_RE.search(text)
        if m_letter_bar:
            letter_tok = m_letter_bar.group(1).strip().casefold()
            explicit_num = (
                _parse_decimal(m_letter_bar.group(2)) if m_letter_bar.group(2) else None
            )
            bar_val = explicit_num or _LETTER_GRADE_TO_GPA_4.get(letter_tok)
            scale_val = Decimal("4.0")

    if bar_val is not None and scale_val is not None:
        gpa_evals: list[StatementEvaluation] = []
        for rec in records:
            raw_grade_str = str(getattr(rec, "grade", "") or "").strip()
            country_code = str(getattr(rec, "country_code", "") or "").strip().upper()
            rec_grade, rec_scale_str, custom_lbl = _resolve_record_grade_and_scale(rec)
            rec_is_inverted = _is_german_inverted_scale(rec_scale_str, country_code)
            rec_bounds = (
                None
                if rec_is_inverted
                else _parse_scale_bounds(rec_scale_str, country_code)
            )
            rec_scale = (
                rec_bounds[0]
                if rec_bounds is not None
                else (None if rec_is_inverted else _extract_scale_max(rec_scale_str))
            )
            same_scale_direct = (
                rec_grade is not None
                and rec_scale == scale_val
                and (rec_bounds is None or not rec_bounds[2])
                and not (
                    scale_val == Decimal("100")
                    and country_code in {"GB", "UK", "IE", "AU", "NZ"}
                    and bar_val > Decimal("70")
                )
            )
            if same_scale_direct and rec_grade is not None:
                sat = rec_grade >= bar_val
                gpa_evals.append(
                    StatementEvaluation(
                        outcome="SATISFIED" if sat else "FAILED",
                        status_text=(
                            f"{'Met' if sat else 'Not met'} — counted "
                            f"{custom_lbl or f'GPA/grade {rec_grade} / {rec_scale}'} "
                            f"against required {bar_val} / {scale_val}."
                        ),
                    )
                )
            else:
                bav_rec = _bavarian_from_record(
                    rec_grade,
                    rec_scale_str,
                    country_code=country_code,
                    raw_grade_str=raw_grade_str,
                )
                bav_bar = _bavarian_from_record(bar_val, str(scale_val))
                if bav_rec is not None and bav_bar is not None:
                    held_lbl = custom_lbl or (
                        f"{rec_grade}/{rec_scale_str}"
                        if rec_grade is not None and rec_scale_str
                        else (raw_grade_str or rec_scale_str)
                    )
                    prefix_lbl = held_lbl if custom_lbl else f"GPA/grade {held_lbl}"
                    if bav_rec <= bav_bar - Decimal("0.2"):
                        gpa_evals.append(
                            StatementEvaluation(
                                outcome="SATISFIED",
                                status_text=(
                                    f"Met — counted {prefix_lbl} "
                                    f"(≈ {bav_rec} Bavarian) against required "
                                    f"{bar_val}/{scale_val} (≈ {bav_bar} Bavarian)."
                                ),
                            )
                        )
                    elif bav_rec <= bav_bar + Decimal("0.2"):
                        gpa_evals.append(
                            StatementEvaluation(
                                outcome="BORDERLINE",
                                status_text=(
                                    f"Borderline — counted {prefix_lbl} "
                                    f"(≈ {bav_rec} Bavarian) against "
                                    f"required {bar_val}/{scale_val} (≈ {bav_bar} Bavarian)."
                                ),
                            )
                        )
                    else:
                        gpa_evals.append(
                            StatementEvaluation(
                                outcome="FAILED",
                                status_text=(
                                    f"Not met — counted {prefix_lbl} "
                                    f"(≈ {bav_rec} Bavarian) against required "
                                    f"{bar_val}/{scale_val} (≈ {bav_bar} Bavarian)."
                                ),
                            )
                        )
        if gpa_evals:
            return max(gpa_evals, key=lambda e: _OUTCOME_RANK.get(e.outcome, 0))

    return None


def _combine_statement_evaluations(
    sub_evals: list[StatementEvaluation],
) -> StatementEvaluation | None:
    if not sub_evals:
        return None
    if len(sub_evals) == 1:
        return sub_evals[0]
    worst = min(sub_evals, key=lambda e: _OUTCOME_RANK.get(e.outcome, 0))
    return StatementEvaluation(
        outcome=worst.outcome,
        status_text=" | ".join(e.status_text for e in sub_evals),
        counted_courses=tuple(c for e in sub_evals for c in e.counted_courses),
        completed_definite_ects=sum((e.completed_definite_ects for e in sub_evals), _ZERO),
        completed_possible_ects=sum((e.completed_possible_ects for e in sub_evals), _ZERO),
        in_progress_ects=sum((e.in_progress_ects for e in sub_evals), _ZERO),
        required_ects=next(
            (e.required_ects for e in sub_evals if e.required_ects is not None), None
        ),
        missing_topics=tuple(t for e in sub_evals for t in e.missing_topics),
    )


def evaluate_program_statement(
    statement_text: str,
    profile: object,
    *,
    kind: str = "COMPETENCY",
    as_of: _date | None = None,
    include_coursework: bool = True,
    only_coursework: bool = False,
) -> StatementEvaluation:
    """Evaluate a `ProgramStatement` (`COMPETENCY`, `LANGUAGE`, `OTHER`) against `profile`
    and its transcript courses, returning a structured `StatementEvaluation` with a human-readable
    `status_text` showing what we counted."""
    text = " ".join(statement_text.strip().split())
    if not text:
        return StatementEvaluation(
            "UNDECIDABLE", "Stated by the programme. Not yet checked against your record."
        )

    sub_evals: list[StatementEvaluation] = []

    if include_coursework:
        # 1. Subject-specific credit or course-count requirement
        pool_rule = parse_subject_pool_rule(text)
        if pool_rule is not None:
            courses = normalize_transcript_courses(profile)
            sub_evals.append(evaluate_subject_pool_rule(pool_rule, courses))

        # 2. Total prior-degree ECTS floor ("Bachelor's degree of at least 180 ECTS" / "240 ECTS")
        m_deg_ects = _TOTAL_DEGREE_CREDITS_RE.search(text)
        if m_deg_ects:
            deg_ects_str = next((g for g in m_deg_ects.groups() if g), "")
            deg_ects = _parse_decimal(deg_ects_str)
            if deg_ects is not None:
                sub_evals.append(_evaluate_total_degree_credits(deg_ects, profile))

    if only_coursework:
        combined_cw = _combine_statement_evaluations(sub_evals)
        if combined_cw is not None:
            return combined_cw
        return StatementEvaluation(
            "UNDECIDABLE", "Stated by the programme. Not yet checked against your record."
        )

    # 3. GRE / GMAT standardized test requirement (including GPA waivers)
    m_gre = _GRE_QUANT_RE.search(text)
    m_gmat = _GMAT_BAR_RE.search(text)
    grade_check_text = text
    if m_gre or m_gmat:
        m_waiver_gpa = re.search(
            r"waived\s+(?:for\s+applicants\s+)?(?:with|if)\s+(?:a\s+)?(?:cumulative\s+)?gpa\s+"
            r"(?:of\s+)?(?:at\s+least\s+|>=?\s*)?(\d[.,]\d)(?:\s*(?:/|out\s+of|on\s+a)\s*"
            r"(\d+(?:[.,]\d+)?))?",
            text,
            re.IGNORECASE,
        )
        gre_ev: StatementEvaluation | None = None
        if m_waiver_gpa:
            grade_check_text = (
                text[: m_waiver_gpa.start()].strip() + " " + text[m_waiver_gpa.end() :].strip()
            ).strip()
            waiver_bar = _parse_decimal(m_waiver_gpa.group(1))
            waiver_scale = (
                _parse_decimal(m_waiver_gpa.group(2))
                if m_waiver_gpa.group(2)
                else Decimal("4.0")
            )
            if waiver_bar is not None and waiver_scale is not None:
                ev_w = _evaluate_grade_or_gpa_statement(
                    f"minimum GPA of {waiver_bar} on a {waiver_scale} scale", profile
                )
                if ev_w is not None and ev_w.outcome == "SATISFIED":
                    gre_ev = StatementEvaluation(
                        outcome="SATISFIED",
                        status_text=(
                            f"Met via GPA waiver — {ev_w.status_text.removeprefix('Met — ')}"
                        ),
                    )
        if gre_ev is None:
            test_label = (
                f"GRE Quantitative >= {m_gre.group(1)}"
                if m_gre
                else f"GMAT >= {m_gmat.group(1) if m_gmat else ''}"
            )
            gre_ev = StatementEvaluation(
                outcome="UNDECIDABLE",
                status_text=(
                    f"Your action — requires {test_label} (test score not yet on your profile)."
                ),
            )
        sub_evals.append(gre_ev)

    # 4. German inverted grade, UK Honours classification, or standard GPA / percentage floor
    ev_grade = _evaluate_grade_or_gpa_statement(grade_check_text, profile)
    if ev_grade is not None:
        sub_evals.append(ev_grade)

    # 5. Work experience requirement ("at least 24 months / 2 years of work experience")
    m_work = _WORK_EXP_BAR_RE.search(text)
    if m_work:
        amt_num = int(m_work.group(1))
        unit_w = m_work.group(2).casefold()
        req_months = amt_num * 12 if "year" in unit_w else amt_num
        raw_exp = getattr(profile, "experience", None)
        if raw_exp is None:
            sub_evals.append(
                StatementEvaluation(
                    outcome="UNDECIDABLE",
                    status_text=(
                        "Not yet checked — work experience is not recorded on your profile."
                    ),
                )
            )
        else:
            exp_records = tuple(raw_exp)
            work_months = sum(
                int(getattr(r, "months", 0))
                for r in exp_records
                if str(getattr(r, "kind", "")) == "WORK"
            )
            intern_months = sum(
                int(getattr(r, "months", 0))
                for r in exp_records
                if str(getattr(r, "kind", "")) == "INTERNSHIP"
            )
            sat = work_months >= req_months
            note = (
                f" (excluding {intern_months} months of internship)"
                if intern_months > 0
                else ""
            )
            sub_evals.append(
                StatementEvaluation(
                    outcome="SATISFIED" if sat else "FAILED",
                    status_text=(
                        f"{'Met' if sat else 'Not met'} — counted {work_months} / {req_months} "
                        f"months of professional work experience{note}."
                    ),
                )
            )

    # 6a. Graduation cutoff date ("degree must be completed by 2027-07-01")
    m_grad_by = _GRADUATION_BY_DATE_RE.search(text)
    if m_grad_by:
        cutoff = _parse_iso_or_human_date(m_grad_by.group(1))
        if cutoff is not None:
            grad_by_evals: list[StatementEvaluation] = []
            for rec in tuple(getattr(profile, "academic_history", ()) or ()):
                comp_on = getattr(rec, "completed_on", None)
                exp_comp = getattr(rec, "expected_completion", None)
                if isinstance(comp_on, _date):
                    sat = comp_on <= cutoff
                    grad_by_evals.append(
                        StatementEvaluation(
                            outcome="SATISFIED" if sat else "FAILED",
                            status_text=(
                                f"{'Met' if sat else 'Not met'} — degree completed on {comp_on} "
                                f"({'on or before' if sat else 'after'} {cutoff} cutoff)."
                            ),
                        )
                    )
                elif isinstance(exp_comp, _date):
                    sat = exp_comp <= cutoff
                    grad_by_evals.append(
                        StatementEvaluation(
                            outcome="IN_PROGRESS" if sat else "FAILED",
                            status_text=(
                                f"{'Conditional (in progress)' if sat else 'Not met'} — expected "
                                f"completion {exp_comp} is {'on or before' if sat else 'after'} "
                                f"{cutoff} cutoff."
                            ),
                        )
                    )
            if grad_by_evals:
                sub_evals.append(max(grad_by_evals, key=lambda e: _OUTCOME_RANK.get(e.outcome, 0)))

    # 6b. Graduation recency window ("graduated no more than 3 years ago")
    m_grad_rec = _GRADUATION_RECENCY_RE.search(text)
    if m_grad_rec:
        max_years = int(m_grad_rec.group(1))
        ref_date = as_of or _date.today()
        grad_rec_evals: list[StatementEvaluation] = []
        for rec in tuple(getattr(profile, "academic_history", ()) or ()):
            comp_on = getattr(rec, "completed_on", None)
            exp_comp = getattr(rec, "expected_completion", None)
            if isinstance(comp_on, _date):
                years_elapsed = (
                    ref_date.year
                    - comp_on.year
                    - ((ref_date.month, ref_date.day) < (comp_on.month, comp_on.day))
                )
                sat = years_elapsed <= max_years
                grad_rec_evals.append(
                    StatementEvaluation(
                        outcome="SATISFIED" if sat else "FAILED",
                        status_text=(
                            f"{'Met' if sat else 'Not met'} — graduated on {comp_on} "
                            f"({years_elapsed} year(s) ago vs. {max_years}-year limit)."
                        ),
                    )
                )
            elif isinstance(exp_comp, _date):
                grad_rec_evals.append(
                    StatementEvaluation(
                        outcome="IN_PROGRESS",
                        status_text=(
                            f"Conditional (in progress) — degree expected on {exp_comp} "
                            f"(within {max_years}-year recency window)."
                        ),
                    )
                )
        if grad_rec_evals:
            sub_evals.append(max(grad_rec_evals, key=lambda e: _OUTCOME_RANK.get(e.outcome, 0)))

    # 7. Language requirement (IELTS / TOEFL / CEFR + subscores + MOI waiver)
    if (
        (kind == "LANGUAGE" and not sub_evals)
        or _IELTS_BAR_RE.search(text)
        or _TOEFL_BAR_RE.search(text)
        or _PTE_BAR_RE.search(text)
        or _DUOLINGO_BAR_RE.search(text)
        or _TESTDAF_BAR_RE.search(text)
        or _DSH_BAR_RE.search(text)
        or _CEFR_BAR_RE.search(text)
    ):
        ev_lang = _evaluate_language_statement(text, profile, as_of=as_of)
        if ev_lang is not None:
            sub_evals.append(ev_lang)

    combined_eval = _combine_statement_evaluations(sub_evals)
    if combined_eval is not None:
        return combined_eval

    # 8. Prior degree field / level check ("Bachelor's degree in Computer Science or Mathematics")
    if re.search(r"\b(?:bachelor|master|degree|graduate)\b", text, re.IGNORECASE):
        from apps.accounts.field_taxonomy import resolve_field_taxonomy
        from apps.funding.eligibility import _DEGREE_ORDER, _degree_level, _field_matches

        m_req_deg = re.search(
            r"\b(bachelor(?:'s)?|undergraduate|master(?:'s)?)\s+degree\b",
            text,
            re.IGNORECASE,
        )
        wanted_level: str | None = None
        if m_req_deg:
            wanted_level = (
                "MASTER" if m_req_deg.group(1).casefold().startswith("master") else "BACHELOR"
            )

        acad_records = tuple(getattr(profile, "academic_history", ()) or ())
        held_level_pairs = [
            (lvl, str(getattr(r, "qualification", "") or "").strip())
            for r in acad_records
            if (lvl := _degree_level(str(getattr(r, "qualification", "")))) is not None
        ]
        if wanted_level is not None and held_level_pairs:
            best_lvl, best_qual = max(
                held_level_pairs, key=lambda pair: _DEGREE_ORDER.index(pair[0])
            )
            if _DEGREE_ORDER.index(best_lvl) < _DEGREE_ORDER.index(wanted_level):
                return StatementEvaluation(
                    outcome="FAILED",
                    status_text=(
                        f"Not met — holds {best_qual or best_lvl.title()}, below required "
                        f"{wanted_level.title()} degree."
                    ),
                )

        m_in = re.search(
            r"\b(?:bachelor(?:'s)?|master(?:'s)?|undergraduate|university)?\s*degree\s+in\s+"
            r"([a-zA-Z][a-zA-Z\s,/&-]{2,80}?)"
            r"(?:\.|\s+or\s+a\s+related|\s+or\s+closely|\s+with|\s+comprising|"
            r"\s+worth|\s+of\s+at\s+least|\s+and\s+have|$)",
            text,
            re.IGNORECASE,
        )
        if m_in:
            raw_fields = [
                p.strip()
                for p in re.split(r",|\bor\b", m_in.group(1), flags=re.IGNORECASE)
                if p.strip()
                and p.strip().casefold()
                not in ("related field", "equivalent", "similar", "a related field")
            ]
            prior_fields = [
                str(getattr(r, "field", "") or "").strip()
                for r in acad_records
                if str(getattr(r, "field", "") or "").strip()
            ]
            if raw_fields and prior_fields:
                prior_expanded: list[str] = []
                for pf in prior_fields:
                    pf_res = resolve_field_taxonomy(pf)
                    prior_expanded.extend(
                        (pf, *pf_res.canonical_degree_titles, *pf_res.parent_fields)
                    )
                candidate_fields = tuple(
                    dict.fromkeys(f.casefold() for f in prior_expanded if f)
                )
                wanted_fields: list[str] = []
                for part in (rf.casefold() for rf in raw_fields if rf.strip()):
                    if part not in wanted_fields:
                        wanted_fields.append(part)
                    for syn in resolve_field_taxonomy(part).canonical_degree_titles:
                        syn_cf = syn.casefold()
                        if syn_cf not in wanted_fields:
                            wanted_fields.append(syn_cf)
                if any(
                    _field_matches(part, held_field)
                    for part in wanted_fields
                    for held_field in candidate_fields
                ):
                    return StatementEvaluation(
                        outcome="SATISFIED",
                        status_text=(
                            f"Met — counted degree field ({', '.join(prior_fields)}) against "
                            f"{', '.join(raw_fields)}."
                        ),
                    )
                return StatementEvaluation(
                    outcome="BORDERLINE",
                    status_text=(
                        f"Borderline — prior degree field ({', '.join(prior_fields)}) requires "
                        f"review against required {', '.join(raw_fields)}."
                    ),
                )
        elif wanted_level is not None and held_level_pairs:
            best_lvl, best_qual = max(
                held_level_pairs, key=lambda pair: _DEGREE_ORDER.index(pair[0])
            )
            return StatementEvaluation(
                outcome="SATISFIED",
                status_text=(
                    f"Met — counted {best_qual or best_lvl.title()} against required "
                    f"{wanted_level.title()} degree."
                ),
            )

    # 9. Scholarship / funding status disclaimers ("without scholarship", "self-funded only",
    # "pending EACEA grant renewal"). Evaluated on the applicant requirements pane
    # (`include_coursework=True`); pack-level funding exclusion is handled by Gate 10 and spine.py.
    if include_coursework:
        schol_status = parse_scholarship_status_statement(text)
        if schol_status is not None:
            from apps.funding.validity import intake_matches_target

            status_kind, applies_to = schol_status
            intake_dt = getattr(profile, "intended_intake", None)
            target_yr = intake_dt.year if isinstance(intake_dt, _date) else None
            cohort_lbl = (
                f"the {applies_to} intake" if applies_to != "UNSTATED" else "this intake"
            )
            if not intake_matches_target(applies_to, target_yr):
                return StatementEvaluation(
                    outcome="SATISFIED",
                    status_text=(
                        f"Met — scholarship restriction applies to {applies_to}, not your "
                        f"intended {target_yr} intake."
                    ),
                )
            dep = str(getattr(profile, "funding_dependency", "") or "").upper()
            non_neg = tuple(getattr(profile, "non_negotiables", ()) or ())
            neg_pref = tuple(getattr(profile, "negotiable_preferences", ()) or ())
            unconstrained_opt = dep == "OPTIONAL" and any(
                str(getattr(c, "kind", "")).upper() == "OTHER"
                and str(getattr(c, "value", "")).strip().upper() == "NO_FUNDING_NEEDED"
                for c in (*non_neg, *neg_pref)
            )
            if unconstrained_opt:
                return StatementEvaluation(
                    outcome="SATISFIED",
                    status_text=(
                        f"Met — scholarship notice for {cohort_lbl} does not restrict "
                        "self-funded admission."
                    ),
                )
            if status_kind == "PENDING_RENEWAL":
                return StatementEvaluation(
                    outcome="BORDERLINE",
                    status_text=(
                        f"Conditional — scholarships for {cohort_lbl} are pending external "
                        "grant renewal / approval."
                    ),
                )
            if status_kind == "NO_FULL_SCHOLARSHIP":
                return StatementEvaluation(
                    outcome="BORDERLINE",
                    status_text=(
                        f"Conditional — full scholarships are suspended for {cohort_lbl}; "
                        "only partial / tuition waivers are offered."
                    ),
                )
            if dep == "MANDATORY":
                return StatementEvaluation(
                    outcome="FAILED",
                    status_text=(
                        f"Not met — programme states that {cohort_lbl} is without scholarship "
                        "(self-funded only), and your profile requires mandatory funding."
                    ),
                )
            return StatementEvaluation(
                outcome="BORDERLINE",
                status_text=(
                    f"Note — programme states that {cohort_lbl} is without scholarship "
                    "(self-funded only)."
                ),
            )

        # 10. Erasmus Mundus 12-Month Residency Rule ("more than 12 months over the last 5 years
        # in a Programme Country")
        if _ERASMUS_12_MONTH_RULE_RE.search(text):
            nat = str(getattr(profile, "nationality", "") or "").upper()
            res_country = str(getattr(profile, "country_of_residence", "") or "").upper()
            intake_dt = getattr(profile, "intended_intake", None)
            ref_year = intake_dt.year if isinstance(intake_dt, _date) else _date.today().year
            prog_country_triggers: list[str] = []
            if res_country in _ERASMUS_PROGRAMME_COUNTRIES and res_country != nat:
                prog_country_triggers.append(f"current residence in {res_country}")
            for rec in tuple(getattr(profile, "academic_history", ()) or ()):
                rec_cc = str(getattr(rec, "country_code", "") or "").upper()
                if rec_cc not in _ERASMUS_PROGRAMME_COUNTRIES or rec_cc == nat:
                    continue
                comp_on = getattr(rec, "completed_on", None)
                exp_comp = getattr(rec, "expected_completion", None)
                rec_year = (
                    comp_on.year
                    if isinstance(comp_on, _date)
                    else (exp_comp.year if isinstance(exp_comp, _date) else ref_year)
                )
                if ref_year - rec_year <= 5:
                    qual = str(getattr(rec, "qualification", "") or "degree").strip()
                    prog_country_triggers.append(f"{qual} in {rec_cc} ({rec_year})")
            if nat not in _ERASMUS_PROGRAMME_COUNTRIES and prog_country_triggers:
                return StatementEvaluation(
                    outcome="BORDERLINE",
                    status_text=(
                        "Borderline (12-month residency rule) — Partner Country national with "
                        f"{', '.join(prog_country_triggers)} within the last 5 years; verify "
                        "Programme vs. Partner Country scholarship track."
                    ),
                )
            return StatementEvaluation(
                outcome="SATISFIED",
                status_text=(
                    "Met — no disqualifying Programme Country residence or degree over 12 months "
                    "in the last 5 years recorded on your profile."
                ),
            )

    # 11. Audience-specific application deadlines (Non-EU / visa-requiring vs. EU / EEA)
    m_non_eu_dl = _NON_EU_VISA_DEADLINE_RE.search(text)
    m_eu_dl = _EU_DOMESTIC_DEADLINE_RE.search(text)
    if m_non_eu_dl or m_eu_dl:
        nat = str(getattr(profile, "nationality", "") or "").upper()
        is_eu_eea = nat in _EU_EEA_CH_COUNTRIES
        chosen_raw = (
            (m_eu_dl.group(1) if m_eu_dl else None)
            if is_eu_eea
            else (m_non_eu_dl.group(1) if m_non_eu_dl else None)
        )
        if chosen_raw:
            dl_date = _parse_iso_or_human_date(chosen_raw)
            if dl_date is not None and as_of is not None:
                track_lbl = "EU/EEA" if is_eu_eea else "Non-EU / visa-requiring"
                if as_of > dl_date:
                    return StatementEvaluation(
                        outcome="FAILED",
                        status_text=(
                            f"Not met — your {track_lbl} application deadline ({dl_date}) "
                            f"has passed as of {as_of}."
                        ),
                    )
                return StatementEvaluation(
                    outcome="SATISFIED",
                    status_text=(
                        f"Met — your {track_lbl} application deadline ({dl_date}) "
                        f"is open as of {as_of}."
                    ),
                )

    return StatementEvaluation(
        outcome="UNDECIDABLE",
        status_text="Stated by the programme. Not yet checked against your record.",
    )


def ungraduated_degree_completion(profile: object, ref_date: _date) -> _date | None:
    """If the student has prior degree records on their profile and none is yet
    completed as of `ref_date`, return the pending completion date (or `ref_date`
    sentinel), because a degree-based language proficiency waiver/certificate
    (`evidence_type == "DEGREE"` or Medium of Instruction waiver) only takes
    effect upon graduation."""
    acad = tuple(getattr(profile, "academic_history", ()) or ())
    if not acad:
        return None
    pending: _date | None = None
    for rec in acad:
        comp = getattr(rec, "completed_on", None)
        exp = getattr(rec, "expected_completion", None)
        if isinstance(comp, _date) and comp <= ref_date:
            return None
        if isinstance(comp, _date) and comp > ref_date:
            pending = comp
        elif isinstance(exp, _date):
            pending = exp
        else:
            pending = ref_date
    return pending


def _finalize_language_evidence_verdict(
    item: object,
    profile: object,
    counted_detail: str,
    *,
    requires_official_test: bool,
    as_of: _date | None,
) -> StatementEvaluation:
    avail = getattr(item, "available_by", None)
    ev_type = str(getattr(item, "evidence_type", "") or "").upper()
    lvl_str = str(getattr(item, "level", "") or "").strip()
    intake = getattr(profile, "intended_intake", None)
    ref_date = as_of or _date.today()

    if isinstance(avail, _date) and isinstance(intake, _date) and avail > intake:
        return StatementEvaluation(
            outcome="FAILED",
            status_text=(
                f"Not met — {lvl_str} is available on {avail}, after intended intake {intake}."
            ),
        )
    if isinstance(avail, _date) and avail > ref_date:
        return StatementEvaluation(
            outcome="IN_PROGRESS",
            status_text=f"Conditional (planned by {avail}) — {counted_detail}",
        )
    if ev_type == "DEGREE":
        if ungraduated_degree_completion(profile, ref_date) is not None:
            return StatementEvaluation(
                outcome="IN_PROGRESS",
                status_text=(
                    "Conditional (prior-degree language proficiency waiver/certificate "
                    f"applies upon graduation) — {counted_detail}"
                ),
            )
    if (
        requires_official_test
        and ev_type in ("ATTESTED", "OTHER")
        and not re.search(
            r"\b(?:native|mother\s+tongue|bilingual|first\s+language)\b",
            lvl_str.casefold(),
        )
    ):
        return StatementEvaluation(
            outcome="IN_PROGRESS",
            status_text=(
                "Conditional (self-attested; official test certificate required) — "
                f"{counted_detail}"
            ),
        )
    if requires_official_test and ev_type == "DEGREE":
        return StatementEvaluation(
            outcome="IN_PROGRESS",
            status_text=(
                "Conditional (prior degree taught in English is not an official test "
                f"certificate; IELTS/TOEFL required unless MOI waiver applies) — {counted_detail}"
            ),
        )
    return StatementEvaluation(
        outcome="SATISFIED",
        status_text=f"Met — {counted_detail}",
    )


def _parse_testdaf_tdn_level(text: str) -> int | None:
    s = text.casefold()
    m_tdn = re.search(r"(?:tdn\s*|4\s*x\s*)([345])\b", s)
    if m_tdn:
        return int(m_tdn.group(1))
    m_tot = re.search(r"\b(1[2-9]|20)\b", s)
    if m_tot:
        tot = int(m_tot.group(1))
        return 5 if tot >= 20 else (4 if tot >= 16 else 3)
    m_single = re.search(r"\b([345])\b", s)
    if m_single:
        return int(m_single.group(1))
    return None


def _evaluate_language_statement(
    text: str,
    profile: object,
    *,
    as_of: _date | None = None,
) -> StatementEvaluation | None:
    records = tuple(getattr(profile, "language_evidence", ()) or ())
    m_ielts = _IELTS_BAR_RE.search(text)
    m_toefl = _TOEFL_BAR_RE.search(text)
    m_pte = _PTE_BAR_RE.search(text)
    m_duolingo = _DUOLINGO_BAR_RE.search(text)
    m_testdaf = _TESTDAF_BAR_RE.search(text)
    m_dsh = _DSH_BAR_RE.search(text)
    m_cefr = _CEFR_BAR_RE.search(text)
    has_moi_waiver = bool(_MOI_WAIVER_RE.search(text))
    requires_official_test = bool(
        m_ielts or m_toefl or m_pte or m_duolingo or m_testdaf or m_dsh
    )

    target_lang = "english"
    if m_cefr:
        default_lang = "german" if (m_testdaf or m_dsh) else "english"
        lang_tok = (m_cefr.group(1) or m_cefr.group(4) or default_lang).casefold()
        target_lang = lang_tok
    elif m_testdaf or m_dsh:
        target_lang = "german"
    elif not (m_ielts or m_toefl or m_pte or m_duolingo):
        return None

    matching_ev = [
        item
        for item in records
        if str(getattr(item, "language", "") or "").strip().casefold()
        in (target_lang, target_lang[:2])
    ]

    if has_moi_waiver and target_lang == "english":
        ref_date = as_of or _date.today()
        if any(
            str(getattr(i, "evidence_type", "") or "").upper() == "DEGREE" for i in matching_ev
        ):
            if ungraduated_degree_completion(profile, ref_date) is not None:
                return StatementEvaluation(
                    outcome="IN_PROGRESS",
                    status_text=(
                        "Conditional via Medium of Instruction waiver — prior-degree "
                        "language proficiency waiver/certificate applies upon graduation."
                    ),
                )
            return StatementEvaluation(
                outcome="SATISFIED",
                status_text=(
                    "Met via Medium of Instruction waiver — prior degree taught in English."
                ),
            )
        acad = tuple(getattr(profile, "academic_history", ()) or ())
        anglophone = {"GB", "UK", "US", "CA", "AU", "IE", "NZ"}
        held_cc = [
            str(getattr(r, "country_code", "") or "").upper()
            for r in acad
            if str(getattr(r, "country_code", "") or "").upper() in anglophone
        ]
        if held_cc:
            if ungraduated_degree_completion(profile, ref_date) is not None:
                return StatementEvaluation(
                    outcome="IN_PROGRESS",
                    status_text=(
                        "Conditional via Medium of Instruction waiver — prior degree in "
                        f"{held_cc[0]} applies upon graduation."
                    ),
                )
            return StatementEvaluation(
                outcome="SATISFIED",
                status_text=(
                    "Met via Medium of Instruction waiver — prior degree completed in "
                    f"{held_cc[0]}."
                ),
            )

    if not matching_ev:
        return StatementEvaluation(
            outcome="UNDECIDABLE",
            status_text=(
                f"Not yet checked — no {target_lang.capitalize()} language evidence "
                "on your profile."
            ),
        )

    subscore_candidates = [
        val
        for m in _IELTS_SUBSCORE_RE.finditer(text)
        if (val := _parse_decimal(m.group(1) or m.group(2))) is not None
    ]
    req_ielts_sub = next(
        (v for v in subscore_candidates if Decimal("0") < v <= Decimal("9")), None
    )
    req_toefl_sub = next(
        (v for v in subscore_candidates if Decimal("10") <= v <= Decimal("30")), None
    )

    candidate_evals: list[StatementEvaluation] = []
    for item in matching_ev:
        lvl_str = str(getattr(item, "level", "") or "").strip()
        lvl_lower = lvl_str.casefold()
        cleaned_score_str = re.sub(
            r"\b(?:cefr\s*)?[abc][12]\b|(?:/|out\s+of)\s*(?:9(?:\.0)?|90|120|160)\b",
            " ",
            lvl_lower,
        )

        if m_ielts and "ielts" in lvl_lower:
            req_ielts = _parse_decimal(m_ielts.group(1))
            nums = [
                n
                for tok in re.findall(r"\d+(?:[.,]\d+)?", cleaned_score_str)
                if (n := _parse_decimal(tok)) is not None and Decimal("0") <= n <= Decimal("9")
            ]
            held_ielts = nums[0] if nums else None
            if req_ielts is not None and held_ielts is not None:
                if held_ielts < req_ielts:
                    candidate_evals.append(
                        StatementEvaluation(
                            outcome="FAILED",
                            status_text=(
                                f"Not met — counted {lvl_str} against required IELTS {req_ielts}."
                            ),
                        )
                    )
                elif (
                    req_ielts_sub is not None
                    and len(nums) > 1
                    and (subscores := nums[1:])
                    and min(subscores) < req_ielts_sub
                ):
                    candidate_evals.append(
                        StatementEvaluation(
                            outcome="FAILED",
                            status_text=(
                                f"Not met — counted {lvl_str} (overall {held_ielts} meets "
                                f"{req_ielts}, but lowest subscore {min(subscores)} is below "
                                f"required {req_ielts_sub})."
                            ),
                        )
                    )
                else:
                    candidate_evals.append(
                        _finalize_language_evidence_verdict(
                            item,
                            profile,
                            f"counted {lvl_str} against required IELTS {req_ielts}.",
                            requires_official_test=True,
                            as_of=as_of,
                        )
                    )

        if m_toefl and "toefl" in lvl_lower:
            req_toefl = _parse_decimal(m_toefl.group(1))
            toefl_nums = [
                n
                for tok in re.findall(r"\d+", cleaned_score_str)
                if (n := _parse_decimal(tok)) is not None
            ]
            held_toefl_idx = next(
                (
                    idx
                    for idx, n in enumerate(toefl_nums)
                    if Decimal("30") <= n <= Decimal("120")
                ),
                None,
            )
            held_toefl = toefl_nums[held_toefl_idx] if held_toefl_idx is not None else None
            toefl_subscores = (
                [
                    n
                    for n in toefl_nums[held_toefl_idx + 1 :]
                    if Decimal("0") <= n <= Decimal("30")
                ]
                if held_toefl_idx is not None
                else []
            )
            if req_toefl is not None and held_toefl is not None:
                if held_toefl < req_toefl:
                    candidate_evals.append(
                        StatementEvaluation(
                            outcome="FAILED",
                            status_text=(
                                f"Not met — counted {lvl_str} against required "
                                f"TOEFL {int(req_toefl)}."
                            ),
                        )
                    )
                elif (
                    req_toefl_sub is not None
                    and toefl_subscores
                    and min(toefl_subscores) < req_toefl_sub
                ):
                    candidate_evals.append(
                        StatementEvaluation(
                            outcome="FAILED",
                            status_text=(
                                f"Not met — counted {lvl_str} (overall {int(held_toefl)} meets "
                                f"{int(req_toefl)}, but lowest section {int(min(toefl_subscores))} "
                                f"is below required {int(req_toefl_sub)})."
                            ),
                        )
                    )
                else:
                    candidate_evals.append(
                        _finalize_language_evidence_verdict(
                            item,
                            profile,
                            f"counted {lvl_str} against required TOEFL {int(req_toefl)}.",
                            requires_official_test=True,
                            as_of=as_of,
                        )
                    )

        def _append_exam_verdict(
            held_val: Decimal | int, req_val: Decimal | int, req_label: str
        ) -> None:
            detail = f"counted {lvl_str} against required {req_label}."
            if held_val < req_val:
                candidate_evals.append(
                    StatementEvaluation(outcome="FAILED", status_text=f"Not met — {detail}")
                )
            else:
                candidate_evals.append(
                    _finalize_language_evidence_verdict(
                        item,
                        profile,
                        detail,
                        requires_official_test=True,
                        as_of=as_of,
                    )
                )

        if m_pte and "pte" in lvl_lower:
            req_pte = _parse_decimal(m_pte.group(1))
            held_pte = next(
                (
                    n
                    for tok in re.findall(r"\d+(?:[.,]\d+)?", cleaned_score_str)
                    if (n := _parse_decimal(tok)) is not None
                    and Decimal("10") <= n <= Decimal("90")
                ),
                None,
            )
            if req_pte is not None and held_pte is not None:
                _append_exam_verdict(held_pte, req_pte, f"PTE {int(req_pte)}")

        if m_duolingo and ("duolingo" in lvl_lower or re.search(r"\bdet\b", lvl_lower)):
            req_duo = _parse_decimal(m_duolingo.group(1))
            held_duo = next(
                (
                    n
                    for tok in re.findall(r"\d+", cleaned_score_str)
                    if (n := _parse_decimal(tok)) is not None
                    and Decimal("10") <= n <= Decimal("160")
                ),
                None,
            )
            if req_duo is not None and held_duo is not None:
                _append_exam_verdict(held_duo, req_duo, f"Duolingo {int(req_duo)}")

        if m_testdaf and ("testdaf" in lvl_lower or "tdn" in lvl_lower):
            req_tdn = _parse_testdaf_tdn_level(m_testdaf.group(0))
            held_tdn = _parse_testdaf_tdn_level(lvl_lower)
            if req_tdn is not None and held_tdn is not None:
                _append_exam_verdict(held_tdn, req_tdn, f"TestDaF TDN {req_tdn}")

        if m_dsh and "dsh" in lvl_lower:
            req_dsh = int(m_dsh.group(1))
            m_held_dsh = re.search(r"dsh[\s-]*([123])\b", lvl_lower)
            if m_held_dsh:
                _append_exam_verdict(int(m_held_dsh.group(1)), req_dsh, f"DSH-{req_dsh}")

    if candidate_evals:
        best_direct = max(candidate_evals, key=lambda e: _OUTCOME_RANK.get(e.outcome, 0))
        if best_direct.outcome in ("SATISFIED", "IN_PROGRESS"):
            return best_direct

    from apps.funding.eligibility import (
        _CEFR,
        _extract_test_and_score,
        _level_to_cefr,
        _to_ielts_equiv,
    )

    wanted_equivs: list[tuple[float, str]] = []
    if not m_cefr:
        for m_exam, exam_key, exam_label in (
            (m_ielts, "ielts", "IELTS"),
            (m_toefl, "toefl", "TOEFL"),
            (m_pte, "pte", "PTE"),
            (m_duolingo, "duolingo", "Duolingo"),
        ):
            if m_exam:
                req_val = _parse_decimal(m_exam.group(1))
                if req_val is not None:
                    eq = _to_ielts_equiv(exam_key, float(req_val))
                    if eq is not None:
                        wanted_equivs.append((eq, f"{exam_label} {req_val}"))

    wanted_cefr: str | None = None
    wanted_bar = ""
    if m_cefr:
        cefr_tok = (m_cefr.group(2) or m_cefr.group(3) or "").upper()
        wanted_cefr = cefr_tok if cefr_tok in _CEFR else None
        wanted_bar = f"{target_lang.capitalize()} {cefr_tok}"
    else:
        for m_exam, probe_str, bar_lang in (
            (m_ielts, f"IELTS {m_ielts.group(1)}" if m_ielts else "", "English"),
            (m_toefl, f"TOEFL {m_toefl.group(1)}" if m_toefl else "", "English"),
            (m_pte, f"PTE {m_pte.group(1)}" if m_pte else "", "English"),
            (m_duolingo, f"Duolingo {m_duolingo.group(1)}" if m_duolingo else "", "English"),
            (m_testdaf, m_testdaf.group(0) if m_testdaf else "", "German"),
            (m_dsh, m_dsh.group(0) if m_dsh else "", "German"),
        ):
            if m_exam:
                wanted_cefr = _level_to_cefr(probe_str)
                if wanted_cefr:
                    wanted_bar = f"{bar_lang} {wanted_cefr}"
                break

    if wanted_cefr and wanted_bar:
        for item in matching_ev:
            lvl_str = str(getattr(item, "level", "") or "").strip()
            lvl_lower = lvl_str.casefold()
            if (
                (m_ielts and "ielts" in lvl_lower)
                or (m_toefl and "toefl" in lvl_lower)
                or (m_pte and "pte" in lvl_lower)
                or (m_duolingo and ("duolingo" in lvl_lower or re.search(r"\bdet\b", lvl_lower)))
                or (m_testdaf and ("testdaf" in lvl_lower or "tdn" in lvl_lower))
                or (m_dsh and "dsh" in lvl_lower)
            ):
                continue
            held_ts = _extract_test_and_score(lvl_str)
            if held_ts is not None and wanted_equivs:
                held_eq = _to_ielts_equiv(*held_ts)
                if held_eq is not None:
                    min_req_eq, min_req_label = min(wanted_equivs, key=lambda pair: pair[0])
                    if held_eq >= min_req_eq:
                        candidate_evals.append(
                            _finalize_language_evidence_verdict(
                                item,
                                profile,
                                (
                                    f"counted {target_lang.capitalize()} ({lvl_str}) "
                                    f"against {min_req_label}."
                                ),
                                requires_official_test=requires_official_test,
                                as_of=as_of,
                            )
                        )
                    else:
                        candidate_evals.append(
                            StatementEvaluation(
                                outcome="FAILED",
                                status_text=(
                                    f"Not met — counted {target_lang.capitalize()} ({lvl_str}) "
                                    f"against {min_req_label}."
                                ),
                            )
                        )
                    continue
            held_cefr = _level_to_cefr(lvl_str)
            if held_cefr is None:
                ev_type = str(getattr(item, "evidence_type", "") or "").upper()
                if re.search(
                    r"\b(?:native|mother\s+tongue|bilingual|first\s+language)\b", lvl_lower
                ):
                    held_cefr = "C2"
                elif ev_type == "DEGREE" and not requires_official_test:
                    held_cefr = "C1"
            if held_cefr is None:
                continue
            if _CEFR.index(held_cefr) >= _CEFR.index(wanted_cefr):
                candidate_evals.append(
                    _finalize_language_evidence_verdict(
                        item,
                        profile,
                        f"counted {target_lang.capitalize()} ({lvl_str}) against {wanted_bar}.",
                        requires_official_test=requires_official_test,
                        as_of=as_of,
                    )
                )
            else:
                candidate_evals.append(
                    StatementEvaluation(
                        outcome="FAILED",
                        status_text=(
                            f"Not met — counted {target_lang.capitalize()} ({lvl_str}) "
                            f"against {wanted_bar}."
                        ),
                    )
                )

    if candidate_evals:
        return max(candidate_evals, key=lambda e: _OUTCOME_RANK.get(e.outcome, 0))

    return None
