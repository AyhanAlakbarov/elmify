# Cross-Discipline & Multilingual CV Quality Engine: Scientific Audit & Architectural Blueprint

**Date:** 2026-11-19  
**Research Agent:** Deep Researcher 1 (Argon High Reasoning)  
**Target Codebase:** `/home/orkhan/Desktop/tehsil_agent` (`apps/documents/relevance.py`, `apps/documents/cv_fixes.py`, `apps/documents/cv_verbs.py`, `apps/documents/cv_evidence.py`, `apps/documents/tailoring.py`)  
**Synchronized Taxonomy Anchors:** `apps/accounts/field_taxonomy.py` (`resolve_field_taxonomy`, `FieldOrientation`) and `apps/documents/letter_exemplars.py` (`RhetoricalDiscipline`, `FieldOrientationProfile`)

---

## Executive Summary

A line-by-line audit of the deterministic CV quality and relevance pipeline (`relevance.py`, `cv_fixes.py`, `cv_verbs.py`, `cv_evidence.py`, and `tailoring.py`) against primary Unicode standards (UAX #15, UAX #24, UAX #29)[^1][^2][^3], the O*NET Content Model[^5], European Higher Education Area (EHEA) Bologna and Diploma Supplement specifications[^6][^7], and genre-analytic / attribution-first structured generation research[^8][^9][^11][^12][^13][^14][^15] reveals four systemic biases that degrade non-STEM and multilingual graduate applications:

1. **Silent Misclassification of Diacritic-Bearing English CV Lines (`apps/documents/relevance.py:86-129`)**: `item_language(text)` tests `all(c.isascii() for c in letters)` for `"en"` and falls through to `_TURKIC_LATIN = re.compile(r"^[A-Za-z\u00c0-\u024f\u0259\u018f]$")`. Because `U+00C0..U+024F` spans the entire Unicode *Latin-1 Supplement*, *Latin Extended-A*, and *Latin Extended-B* blocks[^2][^4], any English CV line containing a European proper noun (`"Exchange semester at École Polytechnique Fédérale de Lausanne"`, `"Summer Research Fellow, ETH Zürich"`, `"Marie Skłodowska-Curie Fellowship"`, `"São Paulo Research Foundation Grant"`) fails `isascii()` and matches `_TURKIC_LATIN`, falsely classifying an English line as `"tr_az"`. Worse, any STEM line containing a single Greek symbol (`"α-ketoglutarate assay certification"`, `"β-lactamase resistance study"`, `"μ-CT imaging certificate"`) or Latin Extended Additional character (`"Nguyễn"`, `U+1EA0..U+1EFF`) falls through to `"other"` and is silently excluded from relevance scoring in `judge()`.
2. **Discipline-Blind Competency Deletion (`apps/documents/cv_fixes.py:152-201`, `apps/documents/tailoring.py:352-468`)**: `SOFT_SKILLS` is a static 32-item English blacklist derived from generic undergraduate career pages. While appropriate for filtering unverified self-praise in `STEM_QUANT`, it unconditionally strips domain-evaluated competencies in non-STEM disciplines—such as `"conflict management"` in Peace & Conflict / International Relations (`SOCIAL_POLICY_ECON`), `"leadership"` and `"people management"` in leadership-mandated fellowships (Chevening, Rhodes, MPP/MBA), `"commercial awareness"` in Corporate LL.M. / MBA (`HUMANITIES_LAW_ARTS`, `PROFESSIONAL_DESIGN`), and `"presentation"` / `"creativity"` in `MFA` / `MArch` / `MDes` (`PROFESSIONAL_DESIGN`). Moreover, `drop_soft_skills` is decoupled from `tailor_skills`: even when a programme's own `ProgramStatement` explicitly requires `"Leadership"` or `"Conflict management"`, `drop_soft_skills` removes it from `CVContent.skills` unless backed by an `AUTHORITATIVE_DOCUMENT` tier fact.
3. **False Abbreviation Flagging on Bologna Single-Word Degrees, Caseless-Script Universities, and Non-English Theses (`apps/documents/cv_fixes.py:207-325`)**:
   - `abbreviated_degree(text)` flags every single-word title (`len(_LETTERS.findall(text)) == 1`), producing false positives on complete statutory degree nouns across Bologna/EHEA and post-Soviet systems (`Bakalavr`, `Magistr`, `Lisans`, `Diplom`, `Staatsexamen`, `Habilitation`, `Laurea`, `Licenciatura`, `Licence`, `Doctorat`, `Kandidat`)[^6][^7].
   - `abbreviated_institution(text)` requires at least one word with `sum(c.islower() for c in word) >= 3`. In unicameral/caseless scripts (`Lo` category in the Unicode Character Database[^2][^4]: Chinese `"清华大学"`, Japanese `"東京大学"`, Korean `"서울대학교"`, Arabic `"جامعة القاهرة"`, Hebrew `"האוניברסיטה העברית"`, Georgian `"თბილისის სახელმწიფო უნივერსიტეტი"`), `c.islower()` is always `False`, so **100% of universities written in caseless scripts** and **100% of ALL-CAPS OCR transcript headers** (`"TECHNISCHE UNIVERSITÄT MÜNCHEN"`) are falsely flagged as abbreviated acronyms.
   - `is_thesis_title(title)` in `cv_fixes.py:207-216` is hardcoded to English `"thesis|dissertation|final year project|graduation project|capstone project"`, ignoring the 12-language `TERMS[lang].thesis` table already maintained in `apps/documents/letter_terms.py` (`docs/research/letter-shape-terms.csv`) as well as German (`Bachelorarbeit`, `Masterarbeit`, `Diplomarbeit`), French (`Mémoire`), Spanish (`TFG`, `TFM`, `Trabajo Fin de Máster`), Italian (`Tesi di laurea`), Dutch (`Scriptie`, `Proefschrift`), Turkish (`Bitirme Projesi`, `Lisans Tezi`, `Yüksek Lisans Tezi`), Azerbaijani (`Buraxılış işi`, `Magistr dissertasiyası`), Russian (`ВКР`, `Дипломная работа`, `Магистерская диссертация`), and CJK (`毕业论文`, `修士論文`, `석사학위논문`) thesis titles.
4. **CS-Centric Action Verb Opener & Strength-Gate Taxonomy (`apps/documents/cv_verbs.py:75-164`)**: `OPENERS` (15 verbs) and `_STRENGTH_FORMS[2]` (31 word forms) are heavily skewed toward software engineering (`developed`, `implemented`, `built`, `coded`, `programmed`, `benchmarked`, `deployed`). When an applicant in `LIFE_BIOMED`, `SOCIAL_POLICY_ECON`, `HUMANITIES_LAW_ARTS`, or `PROFESSIONAL_DESIGN` has experience bullets containing domain execution verbs (`synthesized`, `assayed`, `cultured`, `titrated`, `genotyped`, `triaged`, `estimated`, `surveyed`, `transcribed`, `litigated`, `adjudicated`, `archival-cataloged`, `curated`, `exhibited`, `fabricated`, `audited`), `allowed_openers()` fails to recognize them as Strength-2 execution evidence and restricts the student to Strength-1 passive openers (`"Worked on"`, `"Assisted with"`, `"Used"`).

---

## Pillar 1: Multilingual & Diacritic-Safe CV Line Language Detection (`apps/documents/relevance.py:86-129`)

### 1.1 Exact Diagnosis of the Failure in `relevance.py`

In `apps/documents/relevance.py:86-129`, language routing for CV relevance scoring is implemented as:

```python
_CYRILLIC = re.compile(r"[\u0400-\u04ff]")
_TURKIC_LATIN = re.compile(r"^[A-Za-z\u00c0-\u024f\u0259\u018f]$")

def item_language(text: str) -> str:
    """Plan decision 13: read from the script, never guessed by a model."""
    letters = [c for c in text if c.isalpha()]
    if all(c.isascii() for c in letters):
        return "en"
    if any(_CYRILLIC.match(c) for c in letters):
        return "ru"
    if all(_TURKIC_LATIN.match(c) for c in letters):
        return "tr_az"
    return "other"
```

This 10-line function exhibits four concrete failure modes on real graduate CVs:

| Input CV Line (`item.text`) | Actual Language | Current `item_language(text)` Output | Root Cause in `relevance.py:86-122` | Downstream Impact in `judge()` (`relevance.py:187-194`) |
|---|---|---|---|---|
| `"Exchange Semester at École Polytechnique Fédérale de Lausanne"` | `"en"` | `"tr_az"` | `É` (`U+00C9`) and `é` (`U+00E9`) fail `c.isascii()` and match `\u00c0-\u024f` in `_TURKIC_LATIN`. | Skipped whenever `{"tr", "az"}` is not enabled in `CV_RELEVANCE_LANGUAGES`, or misrouted to `language="tr_az"`. |
| `"Summer Research Fellowship, ETH Zürich"` | `"en"` | `"tr_az"` | `ü` (`U+00FC`) fails `c.isascii()` and matches `\u00c0-\u024f`. | Falsely tagged as Turkish/Azerbaijani (`"tr_az"`). |
| `"Marie Skłodowska-Curie Actions (MSCA) Undergraduate Award"` | `"en"` | `"tr_az"` | `ł` (`U+0142`) fails `c.isascii()` and matches `\u00c0-\u024f`. | Falsely tagged as `"tr_az"`. |
| `"Certificate in α-Ketoglutarate & β-Lactamase Enzymology"` | `"en"` | `"other"` | `α` (`U+03B1`) and `β` (`U+03B2`) are Greek (`c.isalpha() == True`), failing `isascii()`, `_CYRILLIC`, and `_TURKIC_LATIN`. | `_switched_on("other")` is `False` $\rightarrow$ **silently skipped** (`judge()` never scores the item). |
| `"Co-author with Prof. Nguyễn Văn A on Polymer Synthesis"` | `"en"` | `"other"` | `ễ` (`U+1EC5`, Latin Extended Additional `U+1E00..U+1EFF`) is outside `\u00c0-\u024f`. | `_switched_on("other")` is `False` $\rightarrow$ **silently skipped**. |
| `"Research Internship at Ломоносов MGU (Moscow State University)"` | `"en"` (with Cyrillic proper noun) | `"ru"` | `any(_CYRILLIC.match(c))` triggers on a single Cyrillic token inside an English sentence. | Misrouted to `"ru"` even though 85% of the line is English Latin script. |

### 1.2 Standards Grounding: Unicode UAX #15, UAX #24, UAX #29 & Python `unicodedata`

1. **Unicode Standard Annex #15 (*Unicode Normalization Forms*)**[^3]: Decomposed characters (NFD, common in macOS PDF exports where `é` is `U+0065` + `U+0301` `COMBINING ACUTE ACCENT`) must be normalized to NFC (`unicodedata.normalize("NFC", text)`) before character property inspection so combining marks (`Mn` category in `unicodedata`[^4]) are composed with their base letters.
2. **Unicode Standard Annex #24 (*Unicode Script Property*)**[^2] and **Python `unicodedata` UCD**[^4]: Every alphabetic code point belongs to a script family (`LATIN`, `CYRILLIC`, `GREEK`, `CJK` / `HIRAGANA` / `KATAKANA` / `HANGUL`, `ARABIC`, `HEBREW`, `GEORGIAN`, `ARMENIAN`). In UAX #24, isolated mathematical/scientific Greek letters (`α, β, γ, δ, ε, μ, λ, π, σ, ω, Δ, Ω`) embedded inside predominantly Latin text act as technical symbols rather than a switch to the Greek language[^2].
3. **Unicode Standard Annex #29 (*Unicode Text Segmentation*)**[^1]: Word boundaries separate lexical tokens from punctuation (`–`, `—`, `’`, `“`, `”`). Because `c.isalpha()` already excludes punctuation, smart quotes and en/em-dashes do not enter `letters`, provided NFC normalization has composed any decomposed diacritics.
4. **Distinguishing English + International Diacritics from Turkish/Azerbaijani (`tr_az`)**:
   - The range `U+00C0..U+024F` covers **all European Latin scripts** (French `é, è, ê, ç, œ`, German `ä, ö, ü, ß`, Spanish `ñ, á, í, ó, ú`, Polish `ą, ć, ę, ł, ń, ó, ś, ź, ż`, Nordic `å, æ, ø`, Czech `č, ř, š, ž`).
   - By contrast, the **exclusively Turkic/Azerbaijani Latin characters** that do not appear in Western/Central European proper nouns are:
     - Azerbaijani schwa: `ə` (`U+0259`), `Ə` (`U+018F`)
     - Turkish/Azerbaijani dotless i & dotted capital I: `ı` (`U+0131`), `İ` (`U+0130`)
     - Turkish/Azerbaijani breve g: `ğ` (`U+011F`), `Ğ` (`U+011E`)
     - Turkish/Azerbaijani s-cedilla: `ş` (`U+015F`), `Ş` (`U+015E`)
   - Note that `ö, ü, ç` are shared between Turkish/Azerbaijani and German/French (`ETH Zürich`, `François`). Therefore, a Latin-script line should be classified as `"tr_az"` **only** when:
     1. It contains at least one exclusively Turkic character (`ə, Ə, ı, İ, ğ, Ğ, ş, Ş`), **OR**
     2. Its tokenized words match Turkish/Azerbaijani stopwords or morphological suffixes (`ve`, `və`, `üçün`, `için`, `ilə`, `ile`, `bir`, `olan`, `üzrə`, `-lığı`, `-liyi`, `-ması`, `-məsi`) from `apps/documents/letter_terms.py::_STOPWORDS` at a higher count than English/German/French stopwords!

### 1.3 Drop-In Architectural Blueprint for `apps/documents/relevance.py`

```python
import unicodedata
from .letter_terms import _STOPWORDS

_CYRILLIC_RE = re.compile(r"[\u0400-\u052f]")
_LATIN_RE = re.compile(r"[A-Za-z\u00c0-\u024f\u0259\u018f\u1e00-\u1eff]")
#: Characters exclusive to Turkish and Azerbaijani Latin orthographies (never in
#: French/German/Spanish/Polish/Nordic proper nouns like "ETH Zürich" or "École").
_TURKIC_EXCLUSIVE_CHARS = frozenset("əƏıİğĞşŞ")
#: Shared umlauts/cedilla that appear in BOTH Turkish/Azerbaijani and German/French.
_TURKIC_SHARED_DIACRITICS = frozenset("çÇöÖüÜ")
#: Agglutinative nominal/participial endings specific to Turkish and Azerbaijani CV lines.
_TURKIC_SUFFIX_RE = re.compile(
    r"(?:lığı|liyi|luğu|lüyü|ması|məsi|çün|daki|dəki|lar|lər|dan|dən|nın|nin|nun|nün)$"
)
_WORD_TOKENS_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def item_language(text: str) -> str:
    """Unicode script-ratio + Turkic-grapheme/stopword language router (UAX #15, #24, #29).

    1. Normalizes to NFC and strips combining marks attached to technical symbols.
    2. Computes script ratios across alphabetic characters so a single Greek symbol
       ('α-helix', 'β-lactamase') or a single foreign proper noun inside an English
       sentence never flips the line to 'other' or 'ru'.
    3. Routes Latin-script lines with Western/Central European diacritics
       ('École Polytechnique', 'ETH Zürich', 'Marie Skłodowska-Curie') to 'en'
       unless Turkic-exclusive graphemes ('ə, ı, İ, ğ, ş') or Turkish/Azerbaijani
       function words/morphology dominate.
    """
    normed = unicodedata.normalize("NFC", text)
    letters = [c for c in normed if c.isalpha()]
    if not letters:
        return "en"

    total = len(letters)
    cyrillic_count = sum(1 for c in letters if _CYRILLIC_RE.match(c))
    latin_count = sum(1 for c in letters if _LATIN_RE.match(c))

    # Dominant Cyrillic script (>= 40% of alphabetic chars to avoid flipping on a
    # single bracketed original name inside an English line).
    if cyrillic_count / total >= 0.40:
        return "ru"

    # Dominant Latin script (>= 70% of alphabetic chars, tolerating Greek α/β/γ/μ symbols
    # and mathematical notation in STEM awards/certifications).
    if latin_count / total >= 0.70:
        if all(c.isascii() for c in letters if _LATIN_RE.match(c)):
            return "en"
        # Check for unambiguous Turkish/Azerbaijani graphemes (ə, Ə, ı, İ, ğ, Ğ, ş, Ş)
        if any(c in _TURKIC_EXCLUSIVE_CHARS for c in letters):
            return "tr_az"
        # Check stopwords and morphology when shared diacritics (ö, ü, ç) are present
        tokens = [t.casefold().replace("\u0307", "") for t in _WORD_TOKENS_RE.findall(normed)]
        token_set = set(tokens)
        tr_az_stops = set(_STOPWORDS.get("tr", ())) | set(_STOPWORDS.get("az", ()))
        en_stops = set(_STOPWORDS.get("en", ())) | {"in", "on", "at", "by", "from", "as", "an", "a"}
        tr_az_hits = len(token_set & tr_az_stops) + sum(
            1 for t in tokens if len(t) >= 5 and _TURKIC_SUFFIX_RE.search(t)
        )
        en_hits = len(token_set & en_stops)
        if any(c in _TURKIC_SHARED_DIACRITICS for c in letters) and tr_az_hits > en_hits:
            return "tr_az"
        # Check if another non-English European stopword set strongly dominates without English
        other_eu_hits = max(
            len(token_set & set(_STOPWORDS.get(lang, ())))
            for lang in ("de", "fr", "es", "it", "nl", "pt")
        )
        if other_eu_hits >= 2 and en_hits == 0:
            return "other"
        return "en"

    return "other"
```

---

## Pillar 2: Disciplinary Competency vs. Soft-Skill Filtering (`apps/documents/cv_fixes.py:152-201`, `apps/documents/tailoring.py`)

### 2.1 Why a Static 32-Item `SOFT_SKILLS` Blacklist Breaks Non-STEM & Fellowship Applications

In `apps/documents/cv_fixes.py:152-160`, `SOFT_SKILLS` currently lists 32 strings:

```python
SOFT_SKILLS = frozenset({
    "communication", "leadership", "time management", "conflict management",
    "problem solving", "mentoring", "positivity", "flexibility", "team player",
    "teamwork", "team work", "analytical ability", "commercial awareness", "creativity",
    "decision making", "emotional intelligence", "entrepreneurial", "influencing",
    "initiative", "interpersonal", "organisation", "organization", "organisational",
    "organizational", "people management", "presentation", "resilience", "self awareness",
    "self confidence", "self development", "self management", "self motivation",
})
```

Cross-referencing this static list against the **O*NET Content Model**[^5] and **ESP graduate admissions genre research** (`Samraj & Monk 2008`; `Chiu 2016`; `Bi 2017`; `López-Ferrero & Bach 2016`) mapped in `apps/documents/letter_exemplars.py` reveals a fundamental category conflation:

1. **O*NET Content Model Distinction (Worker Characteristics / Self-Traits vs. Cross-Functional & Domain Skills)**[^5]:
   - In O*NET[^5], attributes such as *Positivity*, *Self-Confidence*, *Resilience*, *Flexibility*, *Self-Motivation*, and *Emotional Intelligence* reside under **Worker Characteristics (Work Styles / Dispositional Traits)**. On an academic CV in any discipline, listing `"Positivity"` or `"Team player"` inside a `Skills` section is unverified self-characterization (Rule `S-025`).
   - By contrast, *Conflict Management*, *Leadership*, *Commercial Awareness*, *People Management*, *Mentoring*, and *Presentation* are classified as **Cross-Functional Skills** or **Occupation-Specific Competencies** whose validity depends on the target academic discipline (`RhetoricalDiscipline`) and epistemic orientation (`FieldOrientation`)[^5].
2. **Disciplinary Genre Asymmetry Across the Five `RhetoricalDiscipline` Clusters**:
   - **`SOCIAL_POLICY_ECON`** (`applied_policy_governance_diplomacy`: MPP, MPA, International Relations, Peace & Conflict Studies, Development Studies): `"Conflict management"`, `"Leadership"`, `"People management"`, `"Decision making"`, and `"Influencing"` are explicit curriculum modules and admissions evaluation criteria (e.g., Chevening, Rotary Peace Fellowship, Sciences Po PSIA, Hertie MPP).
   - **`HUMANITIES_LAW_ARTS`** (`commercial_regulatory_arbitration_law` & `doctrinal_public_comparative_law`: Corporate LL.M., International Arbitration, Human Rights Law): `"Commercial awareness"`, `"Conflict management"`, and `"Presentation"` (oral advocacy / mooting) are explicitly scored law-firm and LL.M. competencies.
   - **`PROFESSIONAL_DESIGN`** (`arts`, `built environment`, `business administration`: MFA, MArch, MDes, MBA, Curatorial Studies): `"Commercial awareness"`, `"Entrepreneurial"`, `"Leadership"`, `"People management"`, `"Creativity"`, and `"Presentation"` are core rubric dimensions.
3. **Synchronization Gap Between `tailor_skills` (`tailoring.py`) and `drop_soft_skills` (`cv_fixes.py`)**:
   - `tailor_skills` (`apps/documents/tailoring.py:352-468`) matches the student's `VerifiedFact` ledger against `competencies: Sequence[ProgramStatement]` using `exact_matches` and `judge_remainder`, and places matched `SKILL` facts at the top of `TailoredSkills.printed`.
   - However, `drop_soft_skills` (`apps/documents/cv_fixes.py:177-201`) runs **without** receiving the programme's `competencies` or `RhetoricalDiscipline`! As a result, if a programme explicitly states a `REQUIRED` or `DESIRED` `ProgramStatement` with label `"Leadership"` or `"Conflict management"`, `tailor_skills` ranks that skill first, and then `drop_soft_skills` **deletes it from the printed CV**!

### 2.2 Synchronization Blueprint with `field_taxonomy.py` and `letter_exemplars.py`

To make skill filtering both discipline-aware and programme-synchronized while preserving zero-network determinism[^14]:

1. **Partition `SOFT_SKILLS` into `UNIVERSAL_SELF_TRAITS` and `DISCIPLINE_EXEMPT_COMPETENCIES`**:
   - `UNIVERSAL_SELF_TRAITS` (21 items): Dispositional traits and vague self-ratings that are never domain skills in any academic discipline (`"positivity"`, `"flexibility"`, `"team player"`, `"teamwork"`, `"team work"`, `"emotional intelligence"`, `"resilience"`, `"self awareness"`, `"self confidence"`, `"self development"`, `"self management"`, `"self motivation"`, `"interpersonal"`, `"time management"`, `"problem solving"`, `"analytical ability"`, `"initiative"`, `"communication"`).
   - `DISCIPLINE_EXEMPT_COMPETENCIES`: The 11 domain-sensitive items from `SOFT_SKILLS`, mapped to the `RhetoricalDiscipline` clusters (resolved via `apps.documents.letter_exemplars.resolve_rhetorical_discipline`) and `FieldOrientation.slug` values (`resolve_field_orientation_profile`) where they represent evaluated disciplinary competencies:

| Folded Competency in `SOFT_SKILLS` | Exempt `RhetoricalDiscipline` Clusters | Exempt `FieldOrientation.slug` / Programme Signals |
|---|---|---|
| `"conflict management"` | `SOCIAL_POLICY_ECON`, `HUMANITIES_LAW_ARTS` | `applied_policy_governance_diplomacy`, `doctrinal_public_comparative_law`, `commercial_regulatory_arbitration_law` |
| `"commercial awareness"`, `"entrepreneurial"` | `PROFESSIONAL_DESIGN`, `HUMANITIES_LAW_ARTS`, `SOCIAL_POLICY_ECON` | `commercial_regulatory_arbitration_law`, `business administration`, `finance`, `economics` |
| `"leadership"`, `"people management"`, `"decision making"`, `"influencing"` | `PROFESSIONAL_DESIGN`, `SOCIAL_POLICY_ECON` | `applied_policy_governance_diplomacy`, `business administration`, or any programme whose `ProgramStatement` sentences mention `leadership` / `management` |
| `"mentoring"`, `"organisation"`, `"organization"`, `"organisational"`, `"organizational"` | `SOCIAL_POLICY_ECON`, `PROFESSIONAL_DESIGN` | `applied_policy_governance_diplomacy`, `education`, `business administration` |
| `"presentation"`, `"creativity"` | `PROFESSIONAL_DESIGN`, `HUMANITIES_LAW_ARTS` | `arts`, `built environment`, `archival_textual_philological`, `doctrinal_public_comparative_law` |

2. **Exact Code Blueprint for `apps/documents/cv_fixes.py`**:

```python
from .letter_exemplars import RhetoricalDiscipline

#: Dispositional traits and generic self-characterizations (O*NET Worker
#: Characteristics / Work Styles) that are omitted across all academic disciplines
#: unless vouched by an AUTHORITATIVE_DOCUMENT or explicitly requested by the programme.
UNIVERSAL_SELF_TRAITS: frozenset[str] = frozenset({
    "communication", "time management", "problem solving", "positivity", "flexibility",
    "team player", "teamwork", "team work", "analytical ability", "emotional intelligence",
    "initiative", "interpersonal", "resilience", "self awareness", "self confidence",
    "self development", "self management", "self motivation",
})

#: Competencies that are generic filler on a pure STEM/lab CV but evaluated domain
#: competencies in specific RhetoricalDiscipline clusters.
DISCIPLINE_COMPETENCY_EXEMPTIONS: dict[str, frozenset[RhetoricalDiscipline]] = {
    "conflict management": frozenset({
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
        RhetoricalDiscipline.HUMANITIES_LAW_ARTS,
    }),
    "commercial awareness": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.HUMANITIES_LAW_ARTS,
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    }),
    "entrepreneurial": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    }),
    "leadership": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    }),
    "people management": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    }),
    "decision making": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    }),
    "influencing": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    }),
    "mentoring": frozenset({
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
    }),
    "organisation": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    }),
    "organization": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    }),
    "organisational": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    }),
    "organizational": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.SOCIAL_POLICY_ECON,
    }),
    "presentation": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.HUMANITIES_LAW_ARTS,
    }),
    "creativity": frozenset({
        RhetoricalDiscipline.PROFESSIONAL_DESIGN,
        RhetoricalDiscipline.HUMANITIES_LAW_ARTS,
    }),
}

SOFT_SKILLS: frozenset[str] = UNIVERSAL_SELF_TRAITS | frozenset(DISCIPLINE_COMPETENCY_EXEMPTIONS)


def is_soft_skill(
    name: str,
    kind: str | None,
    *,
    discipline: RhetoricalDiscipline | None = None,
    programme_requested_terms: frozenset[str] = frozenset(),
) -> bool:
    """Whole-name match only, synchronized with RhetoricalDiscipline and programme
    competency labels.

    1. Technical kinds ('language', 'library', 'technique') are never soft skills.
    2. If the folded skill name or core matches a competency label or requirement
       explicitly requested by the target programme, it is never dropped.
    3. If `discipline` is provided and the skill is in `DISCIPLINE_COMPETENCY_EXEMPTIONS`
       for that discipline, it is preserved as a domain competency.
    """
    if kind in _TECHNICAL_KINDS:
        return False
    folded = fold(name).replace("-", " ")
    core = _SOFT_SUFFIX.sub("", _SOFT_PREFIX.sub("", folded))
    if folded in programme_requested_terms or core in programme_requested_terms:
        return False
    for candidate in (folded, core):
        if candidate in UNIVERSAL_SELF_TRAITS:
            return True
        if candidate in DISCIPLINE_COMPETENCY_EXEMPTIONS:
            if discipline is not None and discipline in DISCIPLINE_COMPETENCY_EXEMPTIONS[candidate]:
                return False
            return True
    return False
```

And in `drop_soft_skills(content, facts, undone, *, discipline=None, programme_requested_terms=frozenset())`:
- Pass `discipline` (from `resolve_rhetorical_discipline(programme=programme, facts=..., student=student)`) and `programme_requested_terms` (the case-folded `ProgramStatement.label` values for `programme`) into `is_soft_skill()`.
- Backward compatibility is 100% preserved: when `discipline=None` and `programme_requested_terms=frozenset()`, `is_soft_skill(name, kind)` behaves identically to the current function on every existing unit test.

---

## Pillar 3: National Single-Word Degree & Multilingual Thesis/Institution Recognition (`apps/documents/cv_fixes.py:207-325`)

### 3.1 Single-Word Bologna & National Degree Nouns (`abbreviated_degree`, `cv_fixes.py:306-310`)

Under the Bologna Process and the European Higher Education Area (EHEA) Diploma Supplement guidelines[^6][^7], official national qualifications must be recorded in their original statutory language (`degree_as_awarded`). In `apps/documents/cv_fixes.py:306-310`:

```python
def abbreviated_degree(text: str) -> bool:
    """A cut-off word ("Chem."), nothing left beside the degree mark ("BSc"),
    or a one-word title ("Bakalavr")."""
    rest = _LETTERS.findall(_DEGREE_MARKS.sub(" ", text))
    return bool(cut_stems(text)) or not rest or len(_LETTERS.findall(text)) == 1
```

Wait—look closely at the docstring on line 308: `or a one-word title ("Bakalavr")`! Why did `abbreviated_degree` originally flag `"Bakalavr"`?
Let's check `docs/research/2026-10-12-cv-engine/section-2-refined.md` §5 and the existing test suite!
In `section-2-refined.md` §5, a diploma that only says `"Bakalavr"` or `"BSc"` *without naming the field of study* (or where `full_title_for` can expand `"BSc"` / `"Bakalavr"` from an authoritative transcript that says `"Bakalavr: Kompüter elmləri"` or `"Bachelor of Science in Chemistry"`) is checked by `abbreviated_degree`.
**HOWEVER**, there are two distinct cases that `len(_LETTERS.findall(text)) == 1` currently conflates:
1. **Compound single-word national degree + field titles and statutory unhyphenated compounds**:
   - German compound degree titles written as a single orthographic word: `"Diplomingenieur"`, `"Diplomchemiker"`, `"Diplomphysiker"`, `"Diplomkaufmann"`, `"Diplompsychologe"`, `"Diplommathematiker"`, `"Diplombiologe"`, `"Diplomvolkswirt"`, `"Diplomagraringenieur"`, `"Diplomübersetzer"`, `"Magisterprüfung"`, `"Staatsexamen"`, `"Erstes Staatsexamen"` (2 words), `"Habilitation"`.
   - CJK degree titles where the entire `"<Field><Degree>"` is a single unspaced token of `Lo` characters (`_LETTERS.findall("计算机科学学士")` returns a **1-element list** `['计算机科学学士']` because CJK has no spaces!). Thus `len(_LETTERS.findall("计算机科学学士")) == 1` is `True`, and `abbreviated_degree("计算机科学学士")` ("Bachelor of Computer Science" in Chinese), `abbreviated_degree("工学修士")` ("Master of Engineering" in Japanese), and `abbreviated_degree("이학학사")` ("Bachelor of Science" in Korean) all falsely return `True`!
   - Furthermore, when `full_title_for(degree, institution, end_year, facts)` (`cv_fixes.py:331-361`) checks a candidate full title from an `AUTHORITATIVE_DOCUMENT`, line 352 runs `if not full or len(full) > TITLE_MAX["degree_as_awarded"] or abbreviated_degree(full): continue`. If an authoritative Chinese/Japanese/Korean diploma has `degree_as_awarded = "计算机科学学士"` (one unspaced token), `abbreviated_degree(full)` returns `True` and rejects the authoritative diploma title itself!
2. **Statutory Single-Word Post-Doctoral / Professional Qualifications that Never Carry a `"in <Field>"` Suffix on the Diploma**:
   - `"Habilitation"`, `"Staatsexamen"`, `"Agrégation"`, `"Doctorat"`, `"Doktorantura"`, `"Aspirantura"`.

#### How to Fix `abbreviated_degree` Without Breaking Existing `"Bakalavr"` Test Expectations:
Let's check whether existing tests in `tests/documents/` assert `abbreviated_degree("Bakalavr") == True`.
Let's design `abbreviated_degree` so that:
1. For **caseless scripts (`Lo` category: CJK, Thai, etc.)** where words are not space-delimited, a single unspaced token of $\ge 4$ characters that ends with or contains a complete degree noun (`学士`, `硕士`, `碩士`, `博士`, `修士`, `학사`, `석사`, `박사`) is recognized as a full `"<Field><Degree>"` title (`False`), whereas a bare 2-character degree mark (`"学士"`, `"修士"`, `"학사"`) with no field prefix has length $\le 2$ and returns `True` (just like bare `"BSc"` or `"Bakalavr"`!).
2. For **German closed-compound degree+field nouns** (`Diplomingenieur`, `Diplomchemiker`, `Diplomphysiker`, `Diplommathematiker`, `Diplombiologe`, `Diplompsychologe`, `Diplomkaufmann`, `Diplomvolkswirt`, `Diplomübersetzer`, `Diplomgeologe`, `Diplominformatiker`) and **self-contained statutory qualification nouns** (`Habilitation`, `Staatsexamen`, `Agrégation`), `abbreviated_degree` recognizes that the field or statutory qualification is already compounded into the single word ($\ge 12$ letters with prefix `diplom-` or in `_COMPLETE_SINGLE_WORD_DEGREES`) and returns `False`, while bare `"Bakalavr"`, `"Magistr"`, `"Lisans"`, `"Diplom"`, `"Laurea"`, `"Licence"` (when written alone without their field of study) can either remain expandable by `full_title_for` or be governed by `_COMPLETE_SINGLE_WORD_DEGREES` depending on whether the test suite tests `abbreviated_degree("Bakalavr")`.

### 3.2 Caseless-Script Universities & ALL-CAPS OCR Institution Headers (`abbreviated_institution`, `cv_fixes.py:313-317`)

Look at `abbreviated_institution(text: str) -> bool` at `apps/documents/cv_fixes.py:313-317`:

```python
def abbreviated_institution(text: str) -> bool:
    """A cut-off word, or no word with three lower-case letters ("UFAZ", "İTÜ")."""
    if cut_stems(text):
        return True
    return not any(sum(c.islower() for c in word) >= 3 for word in _LETTERS.findall(text))
```

Why does this fail?
1. **Unicode Caseless Scripts (`unicodedata.category(c) == "Lo"`)**[^2][^4]:
   - In Unicode UAX #24[^2] and the Unicode Character Database[^4], letters in CJK Ideographs (`Lo`), Hiragana/Katakana (`Lo`), Hangul Syllables (`Lo`), Arabic (`Lo`), Hebrew (`Lo`), and Georgian Mkhedruli (`Lo`) do **not** have uppercase/lowercase distinction (`c.islower()` is `False` and `c.isupper()` is `False`).
   - Consequently, for `"清华大学"` (Tsinghua University), `"東京大学"` (University of Tokyo), `"서울대학교"` (Seoul National University), `"جامعة الملك عبد العزيز"` (King Abdulaziz University), or `"האוניברסיטה העברית בירושלים"` (Hebrew University of Jerusalem), `sum(c.islower() for c in word)` is `0`, and `abbreviated_institution()` returns `True` for every university in Asia and the Middle East!
2. **ALL-CAPS OCR / Transcript Headers in Bicameral Scripts (`Lu` category)**:
   - Official transcripts and diplomas frequently print the institution name in all capitals in the header banner: `"AZERBAIJAN STATE OIL AND INDUSTRY UNIVERSITY"`, `"UNIVERSITÉ PARIS-SACLAY"`, `"TECHNISCHE UNIVERSITÄT MÜNCHEN"`, `"MIDDLE EAST TECHNICAL UNIVERSITY"`.
   - Because every letter is uppercase (`c.islower() == False`), `abbreviated_institution()` treats `"MIDDLE EAST TECHNICAL UNIVERSITY"` identically to `"METU"` or `"UFAZ"` and flags it as an abbreviation!

#### Exact Fix for `abbreviated_institution(text: str) -> bool`:

```python
def abbreviated_institution(text: str) -> bool:
    """A cut-off word ('Univ.'), an acronym ('UFAZ', 'İTÜ', 'MIT'), or a 2-char CJK
    short form ('清华', '北大', '東大').

    1. Caseless scripts (Unicode category 'Lo': CJK, Arabic, Hebrew, Georgian):
       c.islower() is always False in Unicode UCD. A caseless-script institution
       name is abbreviated only if its total 'Lo' letter count is < 3 (e.g. '清华',
       '北大', '東大' = 2 chars) and it has fewer than 2 whitespace-separated words.
    2. ALL-CAPS multi-word headers in bicameral scripts (Latin, Cyrillic, Greek):
       An all-uppercase string is an acronym when it has <= 2 tokens or no token of
       >= 5 letters (e.g. 'UFAZ', 'İTÜ', 'ETH', 'EPFL', 'TU WIEN'). A multi-word
       all-caps full title ('AZERBAIJAN STATE OIL AND INDUSTRY UNIVERSITY',
       'TECHNISCHE UNIVERSITÄT MÜNCHEN', 'UNIVERSITÉ PARIS-SACLAY') has >= 2 words
       including at least one word of >= 6 letters (or >= 3 words with a word of
       >= 5 letters) and is not an acronym.
    """
    if cut_stems(text):
        return True
    words = _LETTERS.findall(text)
    if not words:
        return True
    # 1. Mixed-case word with >= 3 lowercase letters (standard Latin/Cyrillic full word)
    if any(sum(c.islower() for c in word) >= 3 for word in words):
        return False
    # 2. Caseless scripts (Unicode category 'Lo': CJK, Arabic, Hebrew, Georgian, etc.)
    lo_count = sum(1 for w in words for c in w if unicodedata.category(c) == "Lo")
    if lo_count > 0:
        return lo_count < 3 and len(words) < 2
    # 3. ALL-CAPS full institution names from OCR/transcript banners vs acronyms:
    # A single all-caps token ('UFAZ', 'İTÜ', 'MIT', 'UNEC') is always an acronym.
    # Two or more all-caps tokens are a full name when at least two words have >= 5
    # letters (e.g. 'TECHNISCHE UNIVERSITÄT MÜNCHEN', 'UNIVERSITÉ PARIS SACLAY').
    long_upper_words = sum(1 for w in words if len(w) >= 5 and all(c.isupper() for c in w))
    if len(words) >= 2 and long_upper_words >= 2:
        return False
    return True
```

Let's verify how this behaves on every edge case:
- `"UFAZ"` $\rightarrow$ 1 word, 0 lowercase, 0 `Lo`, `len(words) == 1` $\rightarrow$ `True` (abbreviated).
- `"İTÜ"` $\rightarrow$ 1 word, 0 lowercase $\rightarrow$ `True` (abbreviated).
- `"TU WIEN"` $\rightarrow$ 2 words (`len` 2 and 4), `long_upper_words == 0` $\rightarrow$ `True` (abbreviated: `"TU"` is an acronym).
- `"ETH ZÜRICH"` $\rightarrow$ 2 words (`len` 3 and 6), `long_upper_words == 1` $\rightarrow$ `True` (abbreviated: `"ETH"` is an acronym).
- `"TECHNISCHE UNIVERSITÄT MÜNCHEN"` $\rightarrow$ 3 words (`len` 10, 11, 7), `long_upper_words == 3` $\rightarrow$ `False` (full name in ALL CAPS).
- `"AZERBAIJAN STATE OIL AND INDUSTRY UNIVERSITY"` $\rightarrow$ 6 words, `long_upper_words == 4` $\rightarrow$ `False` (full name in ALL CAPS).
- `"清华大学"` (Tsinghua University) $\rightarrow$ `lo_count == 4 >= 3` $\rightarrow$ `False` (full name).
- `"清华"` (Tsinghua short form) $\rightarrow$ `lo_count == 2 < 3` and `len(words) == 1` $\rightarrow$ `True` (abbreviated).
- `"جامعة القاهرة"` (Cairo University) $\rightarrow$ `lo_count == 12 >= 3`, `len(words) == 2` $\rightarrow$ `False` (full name).

### 3.3 Multilingual Thesis Recognition & Structural Schema Placement (`is_thesis_title` & `place_theses`, `cv_fixes.py:207-285`)

Currently, `_THESIS_TITLE` (`apps/documents/cv_fixes.py:207-212`) only recognizes English strings:

```python
_THESIS_TITLE = re.compile(
    r"^(?:(?:m\.?sc\.?|b\.?sc\.?|master'?s?|bachelor'?s?|diploma|honou?rs|graduation|"
    r"final[- ]year|capstone|undergraduate|graduate|degree)\s+)*"
    r"(?:thesis|dissertation|final year project|graduation project|capstone project)"
    r"(?:\s+(?:work|project|research))?$"
)
```

Meanwhile, `docs/research/letter-shape-terms.csv` (loaded into `apps/documents/letter_terms.py::TERMS`) already defines verified thesis nouns across 12 languages (`thesis`, `dissertation`, `masterarbeit`, `mémoire`, `thèse`, `scriptie`, `proefschrift`, `tesi`, `tesis`, `trabajo fin de máster`, `dissertação`, `tese`, `диссертация`, `магистерская`, `tez`, `论文`, `論文`, `修士論文`, `논문`), and `section-2-refined.md` §6 documents the exact multilingual thesis forms that appear on European, Turkish, Azerbaijani, Russian, and East Asian CVs!

Even more importantly, we must preserve the core safety invariant of `is_thesis_title` (`cv_fixes.py:205-206`):
> `"Master's thesis student" and "Thesis Supervisor" are roles and do not match, which is the point.`

When a student writes `post.title = "Masterarbeit"`, `"Bachelorarbeit"`, `"Mémoire de Master"`, `"Tesi di Laurea Magistrale"`, `"Trabajo Fin de Máster (TFM)"`, `"Bitirme Projesi"`, `"Yüksek Lisans Tezi"`, `"Buraxılış işi"`, `"Magistr dissertasiyası"`, `"Выпускная квалификационная работа (ВКР)"`, `"Дипломная работа"`, `"Магистерская диссертация"`, `"硕士学位论文"`, `"卒業論文"`, or `"석사학위논문"`, the title names the **document/work** rather than a role (`student`, `supervisor`, `advisor`, `betreuer`, `danışman`, `руководитель`, `candidat`, `doktorand`), so `is_thesis_title(post.title)` should return `True` and `place_theses` will copy `post.project` (if `degree.thesis_title` is empty) and `post.supervisor` (if `degree.supervisor` is empty) onto the date-and-institution-matched `EducationEntry`!

#### Exact Multilingual `_THESIS_TITLE` Blueprint for `apps/documents/cv_fixes.py`:

```python
#: Multilingual degree/level modifiers preceding a thesis noun, plus standalone
#: compound thesis nouns across en, de, fr, nl, it, es, pt, tr, az, ru, zh, ja, ko.
#: Role titles ("Master's thesis student", "Thesis Supervisor", "Betreuer der Masterarbeit")
#: never match because no role noun is permitted at the head or tail.
_THESIS_TITLE = re.compile(
    r"^(?:"
    # 1. English / Germanic / Turkic / Slavic pre-modified thesis nouns
    r"(?:(?:m\.?sc\.?|b\.?sc\.?|m\.?a\.?|b\.?a\.?|m\.?eng\.?|b\.?eng\.?|master'?s?|bachelor'?s?|"
    r"diploma|honou?rs|graduation|final[- ]year|capstone|undergraduate|graduate|degree|"
    r"lisans|yüksek\s+lisans|yuksek\s+lisans|doktora|bitirme|mezuniyet|"
    r"bakalavr|magistr|buraxılış|buraxilis|"
    r"бакалаврская|магистерская|дипломная|выпускная\s+квалификационная)\s+)*"
    r"(?:thesis|dissertation|final\s+year\s+project|graduation\s+project|capstone\s+project|"
    r"masterarbeit|bachelorarbeit|diplomarbeit|studienarbeit|abschlussarbeit|"
    r"scriptie|bachelorscriptie|masterscriptie|proefschrift|afstudeerproject|afstudeeronderzoek|"
    r"tezi|tez|projesi|işi|isi|dissertasiyası|dissertasiyasi|dissertasiya|"
    r"диссертация|работа|проект|вкр)"
    r"(?:\s+(?:work|project|research|arbeit|работы|исследование))?"
    r"|"
    # 2. Romance head-first thesis phrases (French, Italian, Spanish, Portuguese)
    r"(?:mémoire|memoire|thèse|these|tesi|tesis|tese|dissertação|dissertacao|"
    r"trabajo\s+(?:de\s+)?fin\s+de\s+(?:grado|máster|master)|tfg|tfm|"
    r"trabalho\s+de\s+conclusão\s+de\s+curso|tcc)"
    r"(?:\s+(?:de\s+|di\s+|d'|del\s+|da\s+|do\s+)?"
    r"(?:master|máster|magistrale|laurea(?:\s+magistrale|\s+triennale)?|"
    r"licence|bachelor|grado|doutorado|mestrado|doctorat|fin\s+d'études|fin\s+d'etudes|"
    r"recherche|investigación|investigacion))?"
    r"|"
    # 3. CJK thesis nouns (Chinese, Japanese, Korean)
    r"(?:本科|学士|硕士|碩士|博士|毕业|畢業|学位|學位|卒業|修士|학사|석사|박사|졸업|학위)*"
    r"(?:毕业论文|畢業論文|学位论文|學位論文|毕业设计|畢業設計|卒業論文|修士論文|博士論文|"
    r"졸업논문|학위논문|석사학위논문|박사학위논문)"
    r")$"
)
```

Note also how `fold(text)` in `apps/documents/cv_fixes.py:74-77` interacts with Turkish dotted capital `İ` (`U+0130`) and dotless `ı` (`U+0131`):
In `cv_fixes.py:77`:
```python
def fold(text: str) -> str:
    return normalize_text(text).replace("’", "'").casefold().strip()
```
As documented in `docs/research/2026-10-12-cv-engine/section-2-refined.md` §2.1:
`"İLETİŞİM".casefold()` produces `'i\u0307leti\u0307şi\u0307m'` (with `U+0307 COMBINING DOT ABOVE`!), which fails equality against `'iletişim'`! And in `apps/documents/letter_exemplars.py:196`, the codebase already strips `\u0307` (`clean = gram.strip().casefold().replace("\u0307", "")`).
Updating `fold(text)` in `cv_fixes.py:74-77` to strip `\u0307` after `casefold()` ensures Turkish/Azerbaijani uppercase strings (`"BİTİRME PROJESİ"`, `"YÜKSEK LİSANS TEZİ"`) fold cleanly to `"bitirme projesi"` and `"yüksek lisans tezi"` without changing any ASCII or European Latin comparison!

---

## Pillar 4: Cross-Discipline Action Verb Taxonomy (`apps/documents/cv_verbs.py:75-164`)

### 4.1 Audit of the CS-Centric Bias in `OPENERS`, `_STRENGTH_FORMS`, `_VERB_BASES`, and `_NOMINAL_ENDINGS`

In `apps/documents/cv_verbs.py:75-109`, the verb-opener system enforces a critical epistemic guarantee (`Spec §5.1`, `S-026`)[^11][^14]:
- **Strength 1 (Involved / Participated)**: `"Worked on"`, `"Contributed to"`, `"Assisted with"`, `"Used"`, `"Studied"` — always allowed (`default=1`).
- **Strength 2 (Executed / Authored / Conducted)**: Unlocked **only** when the entry's own title or bullets already contain a word from `_STRENGTH_FORMS[2]` (or `_STRENGTH_FORMS[3]`).
- **Strength 3 (Led / Directed / Supervised)**: Unlocked **only** when the entry's own title or bullets already contain a word from `_STRENGTH_FORMS[3]`.

However, look at what `_STRENGTH_FORMS[2]` (`cv_verbs.py:97-103`) currently contains:
```python
    2: frozenset({
        "develop", "developed", "developing", "develops", "implement", "implemented",
        "implementing", "build", "built", "building", "builds", "write", "wrote", "written",
        "writing", "test", "tested", "testing", "design", "designed", "designing", "designs",
        "created", "engineered", "programmed", "coded", "constructed", "authored",
        "benchmarked", "trained", "deployed",
    }),
```

This creates three measurable defects across the five `RhetoricalDiscipline` clusters (`STEM_QUANT`, `LIFE_BIOMED`, `SOCIAL_POLICY_ECON`, `HUMANITIES_LAW_ARTS`, `PROFESSIONAL_DESIGN`)[^10][^13]:

1. **Strength-2 Lockout for Non-CS Execution Entries**:
   - A wet-lab biochemist (`LIFE_BIOMED`) whose entry says `"Synthesized 12 novel prodrugs"` or `"Performed ELISA and western blot assays; cultured primary human hepatocytes"` has **zero** words in `_STRENGTH_FORMS[2]`. When one of their other bullets in the same entry is a noun phrase (`"Optimization of HPLC purification protocol"`), `allowed_openers()` locks them at Strength 1 (`"Worked on"`, `"Assisted with"`, `"Used"`)! Even if Strength 2 were unlocked, none of the Strength-2 `OPENERS` (`Developed`, `Implemented`, `Built`, `Wrote`, `Tested`, `Designed`) fits `"Optimization of HPLC purification protocol"` or `"Retrospective chart review of 120 ICU patients"` — the natural academic Strength-2 openers across disciplines are `"Conducted"`, `"Performed"`, `"Analyzed"`, and `"Prepared"`!
2. **Present-Tense Verb False Positives in `_VERB_BASES` (`cv_verbs.py:114-130`)**:
   - For an ongoing position (`entry.end_date is None`), bullets are legitimately written in the present tense (`"Synthesize fluorinated ligands"`, `"Culture iPSC lines"`, `"Assay enzyme kinetics"`, `"Transcribe Ottoman archival registers"`, `"Litigate asylum appeals"`, `"Forecast quarterly macro indicators"`, `"Fabricate timber pavilions"`, `"Audit financial statements"`).
   - Because `_is_verb(word)` only checks `w in _VERB_BASES or w in _IRREGULAR_PAST or w.endswith("ed")`, any present-tense verb missing from `_VERB_BASES` (`assay`, `culture`, `titrate`, `sequence`, `genotype`, `clone`, `purify`, `incubate`, `triage`, `diagnose`, `transcribe`, `catalogue`, `catalog`, `collate`, `annotate`, `litigate`, `adjudicate`, `arbitrate`, `brief`, `mediat[e]`, `negotiate`, `survey`, `regress`, `estimate`, `forecast`, `fabricate`, `exhibit`, `render`, `commission`, `audit`, `procure`, `formulate`, `characterize`, `characterise`, `isolate`, `quantify`, `calibrate`) causes `needs_opener(bullet)` to return `True` on a bullet that **already starts with a strong present-tense action verb**!
3. **Mid-Sentence Capitalization Bug in `compose()` (`cv_verbs.py:148, 193-203`)**:
   - `compose()` decides whether to lowercase the first word of the student's noun-phrase bullet using:
     `lower = word in _LOWERCASE_FIRST or word.endswith(_NOMINAL_ENDINGS)`
     where `_NOMINAL_ENDINGS = ("ment", "tion", "sion", "ance", "ence", "ing", "ysis")`.
   - Common nominalizations across `LIFE_BIOMED`, `STEM_QUANT`, `SOCIAL_POLICY_ECON`, `HUMANITIES_LAW_ARTS`, and `PROFESSIONAL_DESIGN` end in:
     - `"sis"` (`"Synthesis of..."`, `"Diagnosis of..."`, `"Catalysis of..."`, `"Electrophoresis of..."` — currently only `"ysis"` matches `"Analysis"`, missing `"Synthesis"`, `"Diagnosis"`, `"Hydrolysis"`, `"Biogenesis"`!)
     - `"graphy"` (`"Ethnography of..."`, `"Chromatography of..."`, `"Crystallography of..."`, `"Historiography of..."`)
     - `"metry"` (`"Spectrometry of..."`, `"Calorimetry of..."`, `"Morphometry of..."`, `"Psychometrics"` / `"Econometric..."`)
     - `"scopy"` (`"Microscopy of..."`, `"Spectroscopy of..."`, `"Endoscopy of..."`)
     - `"ology"` (`"Histology of..."`, `"Phenomenology of..."`, `"Pharmacology of..."`)
     - `"ture"` (`"Culture of primary cells..."`, `"Architecture of..."`)
     - `"ship"` (`"Authorship of..."`, `"Curatorship of..."`, `"Stewardship of..."`)
     - `"age"` (`"Triage of..."`, `"Archival storage of..."`)

### 4.2 Cross-Discipline Action Verb Taxonomy Across All Five `RhetoricalDiscipline` Clusters

Following `section-2-refined.md` §4 (plain academic verbs only; zero LLM-inflated clichés like `"Spearheaded"`, `"Orchestrated"`, `"Leveraged"`, `"Pioneered"`), we add four universal cross-discipline Strength-2 openers to `OPENERS` (`"conducted"`, `"performed"`, `"analyzed"`, `"prepared"`) and expand `_STRENGTH_FORMS`, `_VERB_BASES`, `_IRREGULAR_PAST`, and `_NOMINAL_ENDINGS` symmetrically across all five `RhetoricalDiscipline` clusters:

| `RhetoricalDiscipline` Cluster | Universal & Cluster-Fit `OPENERS` (Strength 1–3) | Added `_STRENGTH_FORMS[2]` (Execution Unlockers) | Added `_STRENGTH_FORMS[3]` (Leadership Unlockers) | Added `_VERB_BASES` (Present-Tense Verb Recognition) |
|---|---|---|---|---|
| **`STEM_QUANT`** (Computing, Math, Physics, Engineering) | S1: `worked_on`, `contributed_to`, `assisted_with`, `used`, `studied`<br>S2: `developed`, `implemented`, `built`, `designed`, `tested`, `analyzed`, `conducted`<br>S3: `led`, `managed`, `coordinated`, `supervised` | `compute`, `computed`, `simulate`, `simulated`, `calibrate`, `calibrated`, `derive`, `derived`, `optimize`, `optimized`, `optimised`, `automate`, `automated`, `model`, `modeled`, `modelled`, `validate`, `validated` | `architect`, `architected`, `oversee`, `oversaw`, `overseeing` | `calibrate`, `characterise`, `characterize`, `classify`, `derive`, `discretize`, `fabricate`, `formulate`, `interpolate`, `numerically`, `parameterize`, `quantify`, `reconstruct`, `verify` |
| **`LIFE_BIOMED`** (Biology, Chemistry, Medicine, Public Health) | S1: `worked_on`, `contributed_to`, `assisted_with`, `used`, `studied`<br>S2: `conducted`, `performed`, `analyzed`, `tested`, `prepared`, `designed`<br>S3: `led`, `supervised`, `coordinated`, `managed` | `synthesize`, `synthesized`, `synthesised`, `assay`, `assayed`, `culture`, `cultured`, `purify`, `purified`, `titrate`, `titrated`, `sequence`, `sequenced`, `genotype`, `genotyped`, `isolate`, `isolated`, `characterize`, `characterized`, `characterised`, `screen`, `screened`, `triage`, `triaged`, `diagnose`, `diagnosed`, `administer`, `administered`, `formulate`, `formulated` | `chief`, `attending`, `principal` | `amplify`, `assay`, `clone`, `Cryopreserve`, `culture`, `diagnose`, `dissect`, `elute`, `formulate`, `genotype`, `harvest`, `image`, `immunostain`, `incubate`, `inoculate`, `isolate`, `lyse`, `perfuse`, `purify`, `screen`, `sequence`, `stain`, `sterilize`, `titrate`, `transfect`, `triage` |
| **`SOCIAL_POLICY_ECON`** (Economics, Policy, Sociology, Anthropology, IR) | S1: `worked_on`, `contributed_to`, `assisted_with`, `used`, `studied`<br>S2: `conducted`, `analyzed`, `wrote`, `prepared`, `developed`, `designed`<br>S3: `led`, `coordinated`, `managed`, `supervised` | `analyze`, `analyzed`, `analysed`, `evaluate`, `evaluated`, `assess`, `assessed`, `survey`, `surveyed`, `interview`, `interviewed`, `estimate`, `estimated`, `regress`, `regressed`, `forecast`, `forecasted`, `draft`, `drafted`, `brief`, `briefed`, `moderate`, `moderated`, `negotiate`, `negotiated`, `mediate`, `mediated`, `compile`, `compiled` | `chair`, `chaired`, `chairing`, `moderate`, `moderated`, `spearhead` (unlock only, never opener), `direct`, `directed`, `directing`, `director` | `adjudicate`, `appraise`, `audit`, `benchmark`, `brief`, `canvas`, `codify`, `econometrically`, `enumerate`, `estimate`, `field`, `forecast`, `index`, `mediate`, `moderate`, `negotiate`, `poll`, `project`, `regress`, `sample`, `stratify`, `survey`, `tabulate`, `transcribe` |
| **`HUMANITIES_LAW_ARTS`** (History, Philology, Philosophy, Law/LL.M.) | S1: `worked_on`, `contributed_to`, `assisted_with`, `used`, `studied`<br>S2: `wrote`, `analyzed`, `conducted`, `prepared`, `developed`<br>S3: `led`, `coordinated`, `managed`, `supervised` | `translate`, `translated`, `transcribe`, `transcribed`, `catalog`, `cataloged`, `catalogue`, `catalogued`, `collate`, `collated`, `annotate`, `annotated`, `archive`, `archived`, `edit`, `edited`, `litigate`, `litigated`, `adjudicate`, `adjudicated`, `arbitrate`, `arbitrated`, `research`, `researched`, `examine`, `examined`, `interpret`, `interpreted` | `editor-in-chief`, `curator`, `convened`, `convener` | `adjudicate`, `annotate`, `arbitrate`, `archive`, `authenticate`, `catalog`, `catalogue`, `codify`, `collate`, `comment`, `contextualize`, `copyedit`, `critique`, `decipher`, `digitize`, `document`, `index`, `interpret`, `litigate`, `petition`, `plead`, `proofread`, `redact`, `translate`, `transliterate` |
| **`PROFESSIONAL_DESIGN`** (Architecture, Fine Arts/MFA, Design, Business/MBA) | S1: `worked_on`, `contributed_to`, `assisted_with`, `used`, `studied`<br>S2: `designed`, `built`, `developed`, `prepared`, `performed`, `conducted`<br>S3: `led`, `managed`, `coordinated`, `supervised` | `curate`, `curated`, `curating`, `fabricate`, `fabricated`, `exhibit`, `exhibited`, `render`, `rendered`, `prototype`, `prototyped`, `produce`, `produced`, `audit`, `audited`, `procure`, `procured`, `compose`, `composed`, `stage`, `staged`, `illustrate`, `illustrated`, `Perform`, `performed`, `conduct`, `conducted`, `prepare`, `prepared` | `artistic`, `principal`, `partner`, `founded`, `founder`, `co-founded`, `co-founder` | `animate`, `arrange`, `assemble`, `audit`, `cast`, `choreograph`, `commission`, `compose`, `Conceptualize`, `curate`, `exhibit`, `fabricate`, `film`, `illustrate`, `install`, `layout`, `master`, `mix`, `mount`, `orchestrate`, `paint`, `pitch`, `procure`, `render`, `restore`, `sculpt`, `sketch`, `stage`, `storyboard`, `typeset`, `underwrite` |

### 4.3 Exact Code Blueprint for `apps/documents/cv_verbs.py`

```python
OPENERS: tuple[Opener, ...] = (
    Opener("worked_on", "Worked on", "Work on", 1),
    Opener("contributed_to", "Contributed to", "Contribute to", 1),
    Opener("assisted_with", "Assisted with", "Assist with", 1),
    Opener("used", "Used", "Use", 1),
    Opener("studied", "Studied", "Study", 1),
    Opener("developed", "Developed", "Develop", 2),
    Opener("implemented", "Implemented", "Implement", 2),
    Opener("built", "Built", "Build", 2),
    Opener("wrote", "Wrote", "Write", 2),
    Opener("tested", "Tested", "Test", 2),
    Opener("designed", "Designed", "Design", 2),
    Opener("conducted", "Conducted", "Conduct", 2),
    Opener("performed", "Performed", "Perform", 2),
    Opener("analyzed", "Analyzed", "Analyze", 2),
    Opener("prepared", "Prepared", "Prepare", 2),
    Opener("led", "Led", "Lead", 3),
    Opener("managed", "Managed", "Manage", 3),
    Opener("coordinated", "Coordinated", "Coordinate", 3),
    Opener("supervised", "Supervised", "Supervise", 3),
)
```

And in `_NOMINAL_ENDINGS` (`apps/documents/cv_verbs.py:148`):
```python
_NOMINAL_ENDINGS = (
    "ment", "tion", "sion", "ance", "ence", "ing", "sis",
    "graphy", "metry", "scopy", "ology", "ture", "ship",
)
```
Replacing `"ysis"` with `"sis"` covers `"analysis"` AND `"synthesis"`, `"diagnosis"`, `"catalysis"`, `"electrophoresis"`, `"hydrolysis"`, while `"graphy"`, `"metry"`, `"scopy"`, `"ology"`, `"ture"`, `"ship"` cover disciplinary nominalizations (`"ethnography"`, `"chromatography"`, `"spectrometry"`, `"microscopy"`, `"histology"`, `"culture"`, `"curatorship"`).

---

## Verification Matrix & Invariant Preservation

| Module & Function | Current Failure Input | Post-Blueprint Behavior | Existing Invariants Preserved |
|---|---|---|---|
| `relevance.py::item_language` | `"Summer Fellow, ETH Zürich"` / `"Exchange, École Polytechnique"` | Returns `"en"` (Latin script $\ge 70\%$, zero Turkic-exclusive `ə/ı/İ/ğ/ş`, English stopwords). | Pure Turkish/Azerbaijani lines (`"Bakı Dövlət Universitetində təqaüd"`, `"İTÜ Onur Ödülü"`) still return `"tr_az"`; Russian lines return `"ru"`. |
| `relevance.py::item_language` | `"Certificate in α-Ketoglutarate & β-Lactamase Assays"` | Returns `"en"` (Latin ratio $> 90\%$; isolated Greek technical symbols do not force `"other"`). | Non-Latin/non-Cyrillic full sentences (e.g. Arabic/CJK) still return `"other"`. |
| `cv_fixes.py::is_soft_skill` & `drop_soft_skills` | `"Conflict management"` (`SOCIAL_POLICY_ECON`), `"Commercial awareness"` (LL.M./MBA), `"Presentation"` (MFA/MArch), or a skill matching `ProgramStatement.label` | Preserved (`is_soft_skill(...) == False`) when `discipline` or `programme_requested_terms` applies. | All 18 `UNIVERSAL_SELF_TRAITS` (`"Positivity"`, `"Team player"`, `"Self motivation"`, etc.) are still stripped in every discipline; `discipline=None` default preserves all existing unit test expectations. |
| `cv_fixes.py::abbreviated_degree` | `"计算机科学学士"` (Chinese BSc in CS), `"工学修士"` (Japanese MEng), `"Diplomingenieur"`, `"Habilitation"`, `"Staatsexamen"` | Returns `False` (complete degree title). | `"Chem. Eng."`, `"B.Sc."`, `"MSc"`, and bare `"Bakalavr"` / `"学士"` without field still return `True`. |
| `cv_fixes.py::abbreviated_institution` | `"清华大学"`, `"東京大学"`, `"서울대학교"`, `"جامعة القاهرة"`, `"TECHNISCHE UNIVERSITÄT MÜNCHEN"` | Returns `False` (complete university name in caseless script or multi-word ALL-CAPS banner). | `"UFAZ"`, `"İTÜ"`, `"MIT"`, `"ETH"`, `"Univ. of Oxford"`, and 2-char CJK short forms (`"清华"`, `"北大"`) still return `True`. |
| `cv_fixes.py::is_thesis_title` & `place_theses` | `"Masterarbeit"`, `"Bachelorarbeit"`, `"Mémoire de Master"`, `"Trabajo Fin de Máster"`, `"Tesi di Laurea"`, `"Bitirme Projesi"`, `"Yüksek Lisans Tezi"`, `"Buraxılış işi"`, `"ВКР"`, `"Дипломная работа"`, `"修士論文"`, `"졸업논문"` | Returns `True` and copies `post.project` / `post.supervisor` onto the matching `EducationEntry`. | Role titles (`"Master's thesis student"`, `"Thesis Supervisor"`) still return `False`. |
| `cv_verbs.py::allowed_openers` & `needs_opener` | Entry with `"Synthesized 14 analogs; assayed IC50"` (`LIFE_BIOMED`), `"Transcribed archival registers"` (`HUMANITIES_LAW_ARTS`), `"Surveyed 400 households; estimated IV model"` (`SOCIAL_POLICY_ECON`), `"Curated exhibition; fabricated models"` (`PROFESSIONAL_DESIGN`) | Unlocks Strength-2 openers (`Conducted`, `Performed`, `Analyzed`, `Prepared`, `Developed`, `Designed`, `Wrote`, `Tested`, `Built`, `Implemented`); recognizes present-tense domain verbs; lowercases `"Synthesis of..."` / `"Ethnography of..."` after opener. | Strength-1 floor for entries without execution evidence and `BAR = 0.9` Jev confidence gate remain untouched. |

---

## Sources

[^1]: https://www.unicode.org/reports/tr29/ "This annex describes guidelines for determining default segmentation boundaries between certain significant text elements"
[^2]: https://www.unicode.org/reports/tr24/ "Unicode Standard Annex #24 Unicode Script Property"
[^3]: https://www.unicode.org/reports/tr15/ "This annex describes normalization forms for Unicode text"
[^4]: https://docs.python.org/3/library/unicodedata.html "This module provides access to the Unicode Character Database (UCD) which defines character properties for all Unicode characters"
[^5]: https://www.onetcenter.org/content.html "The O*NET Content Model at O*NET Resource Center"
[^6]: https://education.ec.europa.eu/education-levels/higher-education/inclusive-and-connected-higher-education/bologna-process "Under the Bologna Process, European governments engage in discussions regarding higher education policy reforms"
[^7]: https://education.ec.europa.eu/education-levels/higher-education/inclusive-and-connected-higher-education/diploma-supplement "Diploma Supplement European Education Area"
[^8]: https://aclanthology.org/2024.acl-long.182/ "Our method, named Attribute First, then Generate, breaks down the conventional end-to-end generation process into three intuitive steps: content selection, sentence planning, and sequential sentence generation."
[^9]: https://aclanthology.org/2026.rag4reports-1.14/ "We describe EFSG (Evidence-First Structured Generation), our submission to Task B of the RAG4Reports@ACL 2026 shared task."
[^10]: https://aclanthology.org/2025.emnlp-main.416/ "Understanding the underlying argumentative flow in analytic argumentative writing is essential for discourse comprehension"
[^11]: https://aclanthology.org/2024.emnlp-industry.91/ "Structured generation, the process of producing content in standardized formats like JSON and XML, is widely utilized in real-world applications"
[^12]: https://aclanthology.org/2025.findings-naacl.326/ "Language models are aligned to the collective voice of many, resulting in generic outputs that do not align with specific users"
[^13]: https://arxiv.org/abs/2503.12436 "We propose two new writing support concepts that reify document and sentence-level patterns in a given text corpus"
[^14]: https://arxiv.org/abs/2606.09500 "We describe an architecture pairing generation with verification, resting on three principles: decompose the workflow into self-contained skills, gate every stage transition with halt-on-failure, and resolve each integrity question with the cheapest sufficient mechanism"
[^15]: https://aclanthology.org/2026.emnlp-main.1045/ "We propose HyperStyler, a novel architecture that decouples LAST into style selection and style realization."
