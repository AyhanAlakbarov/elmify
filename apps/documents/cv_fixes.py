"""Stage 3 (spec 2026-10-12 §5): automatic CV quality fixes, every one a
constrained edit.

No model writes a sentence here. A fix moves the student's own words (thesis
placement), leaves an item out (soft skills), copies a title from a document
the platform read (full titles), or puts one opening from a fixed list in front
of the student's own line (cv_verbs.py; Jev only chooses which). One controlled
study found invented or inflated claims in half of model-rewritten résumés
under a strict prompt (docs/research/2026-10-12-cv-engine/
2026-10-12-faithful-rewriting-checks.md), which is why nothing freer exists.

Every fix is recorded as an AppliedFix with the original beside it. The
student's undo is a CvFixRevert row, and an undone fix stops applying on the
next generation.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import Membership

from .audit import record_event
from .hygiene import normalize_text
from .letter_exemplars import RhetoricalDiscipline
from .models import CvFixRevert, VerifiedFact
from .schemas import CVContent, EducationEntry, ExperienceEntry
from .verification import (
    Verdict,
    fact_identity,
    fact_payload,
    generatable_facts,
    verify_against_facts,
)

_EXP = VerifiedFact.Category.EXPERIENCE
_SKILL = VerifiedFact.Category.SKILL
#: ExperienceEntry.bullets' own limits (schemas.py): a ledger list outside them
#: is not stamped, so a malformed row can never make a draft fail validation.
_MAX_BULLETS = 12
_MAX_BULLET_CHARS = 500

SOFT_SKILL = "soft_skill"
VERB_OPENER = "verb_opener"
THESIS_PLACEMENT = "thesis_placement"
FULL_TITLE = "full_title"
#: Not a fix: the student said a short name is printed exactly so (Task 10).
ABBREVIATED_NAME = "abbreviated_name"


@dataclass(frozen=True)
class AppliedFix:
    fix: str
    #: subject_of(fix, original): the undo key.
    subject: str
    #: Where in the generated content, e.g. "experience[0].bullets[2]".
    where: str
    #: The student's own text before the fix.
    original: str
    #: What the CV prints instead; "" when the item was left out.
    changed: str
    #: The student undid it, so the CV prints the original.
    undone: bool = False

    def as_json(self) -> dict[str, object]:
        return asdict(self)


def fold(text: str) -> str:
    """Whole-name comparison form: NFC-normalised, curly apostrophe straightened,
    case-folded, with Turkish/Azerbaijani dotted-İ combining dot stripped and
    dotless-ı unified."""
    return (
        normalize_text(text)
        .replace("’", "'")
        .casefold()
        .replace("\u0307", "")
        .replace("ı", "i")
        .strip()
    )


def _payload(fact: VerifiedFact) -> dict[str, object]:
    return fact.payload if isinstance(fact.payload, dict) else {}


def _ledger_bullets(fact: VerifiedFact) -> tuple[str, ...] | None:
    bullets = _payload(fact).get("bullets")
    if not isinstance(bullets, list) or not 0 < len(bullets) <= _MAX_BULLETS:
        return None
    if not all(isinstance(b, str) and 0 < len(b) <= _MAX_BULLET_CHARS for b in bullets):
        return None
    return tuple(bullets)


def stamp_from_ledger(content: CVContent, facts: Sequence[VerifiedFact]) -> CVContent:
    """Spec §5.6: the two values the verifier never compares are copied from the
    ledger after the model returns, the way generation already stamps the
    contact address -- stamping removes the failure mode instead of detecting it.

    - Bullets: an experience entry matching exactly one experience fact by the
      verifier's identity gets that fact's bullets. Without this the model can
      reword a line the student kept and every verdict stays SUPPORTED.
    - Skill headings: a skill gets the category of the skill fact with the same
      folded name, None included, so a heading the model invented is removed.
    """
    experience_facts = [f for f in facts if f.category == _EXP]
    experience = []
    for entry in content.experience:
        identity = fact_identity(_EXP, fact_payload(entry, category=_EXP))
        matches = [f for f in experience_facts if fact_identity(_EXP, _payload(f)) == identity]
        bullets = _ledger_bullets(matches[0]) if len(matches) == 1 else None
        experience.append(entry.model_copy(update={"bullets": bullets}) if bullets else entry)
    headings = {
        fold(str(_payload(f).get("name") or "")): _payload(f).get("category")
        for f in facts
        if f.category == _SKILL
    }
    skills = tuple(
        skill.model_copy(update={"category": headings[fold(skill.name)]})
        if fold(skill.name) in headings
        else skill
        for skill in content.skills
    )
    return content.model_copy(update={"experience": tuple(experience), "skills": skills})


def subject_of(fix: str, text: str) -> str:
    """The undo key for one fix of one piece of text: a digest, never the text."""
    return hashlib.sha256(f"{fix}\x00{fold(text)}".encode()).hexdigest()


def reverted_subjects(student: Membership, fix: str | None = None) -> frozenset[str]:
    rows = CvFixRevert.objects.filter(student=student)
    if fix is not None:
        rows = rows.filter(fix=fix)
    return frozenset(rows.values_list("subject", flat=True))


def remember_revert(student: Membership, fix: str, subject: str) -> None:
    CvFixRevert.objects.get_or_create(student=student, fix=fix, subject=subject)


def forget_revert(student: Membership, subject: str) -> None:
    CvFixRevert.objects.filter(student=student, subject=subject).delete()


#: Dispositional traits and generic self-characterizations (O*NET Worker
#: Characteristics / Work Styles) that are omitted across all academic disciplines
#: unless vouched by an AUTHORITATIVE_DOCUMENT or explicitly requested by the programme.
UNIVERSAL_SELF_TRAITS: frozenset[str] = frozenset({
    "communication", "time management", "problem solving", "positivity", "flexibility",
    "team player", "teamwork", "team work", "analytical ability", "emotional intelligence",
    "initiative", "interpersonal", "resilience", "self awareness", "self confidence",
    "self development", "self management", "self motivation",
})

#: Competencies from the UK National Careers Service / Loughborough lists that are
#: generic filler on a pure STEM/lab CV but evaluated domain competencies in
#: specific RhetoricalDiscipline clusters (O*NET Cross-Functional Skills).
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

#: From the two verified sources in docs/research/2026-10-12-cv-engine/
#: 2026-10-12-cv-wordlists-and-merit-items.md §2 (UK National Careers Service;
#: Loughborough University), partitioned into UNIVERSAL_SELF_TRAITS and
#: DISCIPLINE_COMPETENCY_EXEMPTIONS.
SOFT_SKILLS: frozenset[str] = UNIVERSAL_SELF_TRAITS | frozenset(DISCIPLINE_COMPETENCY_EXEMPTIONS)
_SOFT_PREFIX = re.compile(r"^(?:strong|excellent|good|effective|great)\s+")
_SOFT_SUFFIX = re.compile(r"\s+(?:skills?|abilities)$")
#: Measured or read from the student's own code (SkillEntry.kind): never filler.
_TECHNICAL_KINDS = frozenset({"language", "library", "technique"})


def _matches_programme_requested_term(
    candidates: tuple[str, ...], programme_requested_terms: frozenset[str]
) -> bool:
    if not programme_requested_terms:
        return False
    folded_terms = tuple(fold(t).replace("-", " ") for t in programme_requested_terms if t)
    for cand in candidates:
        if not cand:
            continue
        pattern = re.compile(rf"(?<![^\W\d_]){re.escape(cand)}(?![^\W\d_])")
        if any(cand == term or pattern.search(term) for term in folded_terms):
            return True
    return False


def is_soft_skill(
    name: str,
    kind: str | None,
    *,
    discipline: RhetoricalDiscipline | None = None,
    programme_requested_terms: frozenset[str] = frozenset(),
) -> bool:
    """Whole-name match only, never a substring: "Communication protocols" and
    "Team Foundation Server" are technical skills.

    Synchronized with RhetoricalDiscipline and programme-requested competencies:
    1. Technical kinds ('language', 'library', 'technique') are never soft skills.
    2. If the folded skill name or core matches a competency explicitly requested
       by the target programme, it is preserved.
    3. If `discipline` is provided and the skill is in `DISCIPLINE_COMPETENCY_EXEMPTIONS`
       for that discipline, it is preserved as an evaluated domain competency.
    """
    if kind in _TECHNICAL_KINDS:
        return False
    folded = fold(name).replace("-", " ")
    core = _SOFT_SUFFIX.sub("", _SOFT_PREFIX.sub("", folded))
    if _matches_programme_requested_term((folded, core), programme_requested_terms):
        return False
    for candidate in (folded, core):
        if candidate in UNIVERSAL_SELF_TRAITS:
            return True
        if candidate in DISCIPLINE_COMPETENCY_EXEMPTIONS:
            if (
                discipline is not None
                and discipline in DISCIPLINE_COMPETENCY_EXEMPTIONS[candidate]
            ):
                return False
            return True
    return False


def drop_soft_skills(
    content: CVContent,
    facts: Sequence[VerifiedFact],
    undone: frozenset[str],
    *,
    discipline: RhetoricalDiscipline | None = None,
    programme_requested_terms: frozenset[str] = frozenset(),
) -> tuple[CVContent, tuple[AppliedFix, ...]]:
    """Spec §5.2 (S-025): general qualities listed as skills are left out of the
    Skills section and listed as left out. The ledger keeps them, so the letter
    engine and tailoring still see them. A skill a document vouches for, a
    programme explicitly asks for, or a discipline evaluates as a domain
    competency stays."""
    vouched = {
        fold(str(_payload(f).get("name") or ""))
        for f in facts
        if f.category == _SKILL
        and f.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
    }
    kept, fixes = [], []
    for skill in content.skills:
        if (
            not is_soft_skill(
                skill.name,
                skill.kind,
                discipline=discipline,
                programme_requested_terms=programme_requested_terms,
            )
            or fold(skill.name) in vouched
        ):
            kept.append(skill)
            continue
        subject = subject_of(SOFT_SKILL, skill.name)
        put_back = subject in undone
        fixes.append(
            AppliedFix(SOFT_SKILL, subject, "skills", skill.name, "", undone=put_back)
        )
        if put_back:
            kept.append(skill)
    return content.model_copy(update={"skills": tuple(kept)}), tuple(fixes)


#: section-2-refined.md §6 + 12-language thesis nouns (en, de, fr, nl, it, es, pt,
#: tr, az, ru, zh, ja, ko), matched on the folded title without closing punctuation.
#: "Master's thesis student" and "Thesis Supervisor" are roles and do not match.
_THESIS_TITLE = re.compile(
    r"^(?:"
    r"(?:(?:m\.?sc\.?|b\.?sc\.?|m\.?a\.?|b\.?a\.?|m\.?eng\.?|b\.?eng\.?|master'?s?|bachelor'?s?|"
    r"diploma|honou?rs|graduation|final[- ]year|capstone|undergraduate|graduate|degree|"
    r"lisans|yüksek|yuksek|doktora|bitirme|mezuniyet|"
    r"bakalavr|magistr|buraxiliş|buraxilis|"
    r"бакалаврская|магистерская|дипломная|выпускная|квалификационная)\s+)*"
    r"(?:thesis|dissertation|final\s+year\s+project|graduation\s+project|capstone\s+project|"
    r"masterarbeit|bachelorarbeit|diplomarbeit|studienarbeit|abschlussarbeit|"
    r"scriptie|bachelorscriptie|masterscriptie|proefschrift|afstudeerproject|afstudeeronderzoek|"
    r"tezi|tez|dissertasiyasi|dissertasiya|диссертация|вкр)"
    r"(?:\s+(?:work|project|research|arbeit|работы|исследование))?"
    r"|"
    r"(?:(?:bitirme|mezuniyet|lisans|yüksek|yuksek|bakalavr|magistr|diplom|"
    r"buraxiliş|buraxilis|бакалаврская|магистерская|дипломная|выпускная|квалификационная)\s+)+"
    r"(?:projesi|işi|isi|работа|проект)"
    r"|"
    r"(?:mémoire|memoire|thèse|these|tesi|tesis|tese|dissertação|dissertacao|"
    r"trabajo\s+(?:de\s+)?fin\s+de\s+(?:grado|máster|master)|tfg|tfm|"
    r"trabalho\s+de\s+conclusão\s+de\s+curso|tcc)"
    r"(?:\s+(?:de\s+|di\s+|d'|del\s+|da\s+|do\s+)?"
    r"(?:master|máster|magistrale|laurea(?:\s+magistrale|\s+triennale)?|"
    r"licence|bachelor|grado|doutorado|mestrado|doctorat|fin\s+d'études|fin\s+d'etudes|"
    r"recherche|investigación|investigacion))?"
    r"|"
    r"(?:本科|学士|硕士|碩士|博士|毕业|畢業|学位|學位|卒業|修士|학사|석사|박사|졸업|학위)*"
    r"(?:毕业论文|畢業論文|学位论文|學位論文|毕业设计|畢業設計|卒業論文|修士論文|博士論文|"
    r"졸업논문|학위논문|석사학위논문|박사학위논문)"
    r")$"
)


def is_thesis_title(title: str) -> bool:
    return bool(_THESIS_TITLE.match(fold(title).rstrip(".:;")))


def _thesis_degree(content: CVContent, post: ExperienceEntry) -> int | None:
    """The one degree this thesis was written for: its dates hold the post's
    start, and among those one at the post's employer. None unless exactly one."""
    if post.start_date is None:
        return None
    start = post.start_date
    holding = [
        index
        for index, degree in enumerate(content.education)
        if degree.start_date is not None
        and degree.start_date <= start
        and (degree.end_date is None or start <= degree.end_date)
    ]
    employer = fold(post.employer)
    same_place = [
        index
        for index in holding
        if employer in fold(content.education[index].institution_original)
        or fold(content.education[index].institution_original) in employer
    ]
    pick = same_place or holding
    return pick[0] if len(pick) == 1 else None


def place_theses(
    content: CVContent, undone: frozenset[str]
) -> tuple[CVContent, tuple[AppliedFix, ...]]:
    """Spec §5.4 (S-037a, S-040): a thesis filed as a job prints its title and
    supervisor under the degree. The post stays -- Education entries cannot hold
    bullets -- and a degree that already names a thesis or supervisor is left
    alone. The student's own strings move between two of their own entries."""
    education = list(content.education)
    fixes: list[AppliedFix] = []
    for post in content.experience:
        if not is_thesis_title(post.title):
            continue
        index = _thesis_degree(content, post)
        if index is None:
            continue
        degree = education[index]
        update: dict[str, str] = {}
        if post.project and not degree.thesis_title:
            update["thesis_title"] = post.project
        if post.supervisor and not degree.supervisor:
            update["supervisor"] = post.supervisor
        if not update:
            continue
        subject = subject_of(THESIS_PLACEMENT, f"{post.employer}\x00{post.title}")
        was_undone = subject in undone
        changed = "; ".join(
            f"{'Thesis' if key == 'thesis_title' else 'Supervisor'}: {value}"
            for key, value in update.items()
        )
        fixes.append(
            AppliedFix(
                THESIS_PLACEMENT,
                subject,
                f"education[{index}]",
                f"{post.title}, {post.employer}",
                changed,
                undone=was_undone,
            )
        )
        if not was_undone:
            education[index] = degree.model_copy(update=update)
    return content.model_copy(update={"education": tuple(education)}), tuple(fixes)


#: Degree marks removed before looking for a cut-off word, so "B.Sc." alone is
#: never flagged (section-2-refined.md §5). "Mt" joins them ("Mt. Holyoke").
_DEGREE_MARKS = re.compile(
    r"(?<![^\W\d_])(?:b\.?\s?sc|m\.?\s?sc|b\.?\s?a|m\.?\s?a|b\.?\s?eng|m\.?\s?eng|ph\.?\s?d|"
    r"ll\.?\s?b|ll\.?\s?m|m\.?\s?phil|m\.?\s?res|b\.?\s?tech|m\.?\s?tech|dipl\.?-ing|mba|dr|"
    r"st|prof|mt)\.?(?![^\W\d_])",
    re.IGNORECASE,
)
#: Two or more letters then a full stop: a cut-off word. One letter is an initial.
_CUT_WORD = re.compile(r"(?<![^\W\d_])([^\W\d_]{2,})\.(?=\s|,|\)|$)")
_LETTERS = re.compile(r"[^\W\d_]+")
#: The CV's line budget for a title is the schema's own limit (schemas.py).
TITLE_MAX = {"degree_as_awarded": 200, "institution_original": 300}


_CJK_DEGREE_NOUNS = ("学士", "硕士", "碩士", "博士", "修士", "학사", "석사", "박사")
_STATUTORY_SINGLE_WORD_DEGREES = frozenset({
    "habilitation",
    "staatsexamen",
    "agrégation",
    "agregation",
})


def cut_stems(text: str) -> list[str]:
    return [m.group(1).casefold() for m in _CUT_WORD.finditer(_DEGREE_MARKS.sub(" ", text))]


def abbreviated_degree(text: str) -> bool:
    """A cut-off word ("Chem."), nothing left beside the degree mark ("BSc"),
    or a one-word title ("Bakalavr") unless it is a closed German compound
    degree+field noun ("Diplomingenieur", "Diplomjurist", "Diplomkauffrau"), a
    self-contained statutory qualification ("Habilitation", "Staatsexamen",
    "Agrégation"), or a >=4-char CJK <Field><Degree> title ("计算机科学学士",
    "工学修士", "이학학사")."""
    if cut_stems(text):
        return True
    rest = _LETTERS.findall(_DEGREE_MARKS.sub(" ", text))
    if not rest:
        return True
    words = _LETTERS.findall(text)
    if len(words) == 1:
        word = words[0]
        folded_word = normalize_text(word).casefold().replace("\u0307", "")
        if (
            folded_word in _STATUTORY_SINGLE_WORD_DEGREES
            or (folded_word.startswith("diplom") and len(folded_word) >= 11)
            or folded_word.endswith(("staatsexamen", "habilitation"))
        ):
            return False
        lo_count = sum(1 for c in word if unicodedata.category(c) == "Lo")
        if lo_count >= 4 and any(noun in word for noun in _CJK_DEGREE_NOUNS):
            return False
        return True
    return False


def abbreviated_institution(text: str) -> bool:
    """A cut-off word, an acronym ("UFAZ", "İTÜ", "TU WIEN", "ETH ZÜRICH"), or a
    2-character CJK short form ("清华", "北大"). Complete names in caseless
    Unicode 'Lo' scripts ("清华大学", "東京大学", "서울대학교", "جامعة القاهرة") and
    multi-word ALL-CAPS transcript headers ("TECHNISCHE UNIVERSITÄT MÜNCHEN")
    are not abbreviated."""
    if cut_stems(text):
        return True
    words = _LETTERS.findall(text)
    if not words:
        return True
    if any(sum(c.islower() for c in word) >= 3 for word in words):
        return False
    lo_count = sum(1 for w in words for c in w if unicodedata.category(c) == "Lo")
    if lo_count > 0:
        return lo_count < 3
    long_upper_words = sum(1 for w in words if len(w) >= 5 and all(c.isupper() for c in w))
    if len(words) >= 2 and long_upper_words >= 2:
        return False
    return True


def _stems_in_order(stems: list[str], words: list[str]) -> bool:
    position = 0
    for stem in stems:
        while position < len(words) and not words[position].startswith(stem):
            position += 1
        if position == len(words):
            return False
        position += 1
    return True


def full_title_for(
    degree: str, institution: str, end_year: int | None, facts: Sequence[VerifiedFact]
) -> str | None:
    """Spec §5.3: the full title, only from a document the platform read.

    An AUTHORITATIVE_DOCUMENT education fact qualifies when it is at the same
    institution, ends in the same year (when both state one), is itself not
    abbreviated, fits the line budget, and every cut-off word of the CV's
    title starts a word of it, in order. Exactly one must qualify -- "Chem.
    Eng." could be several titles, and the engine never picks one.
    """
    stems = cut_stems(degree)
    found: list[str] = []
    for fact in facts:
        if (
            fact.category != VerifiedFact.Category.EDUCATION
            or fact.source_tier != VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT
        ):
            continue
        payload = _payload(fact)
        full = str(payload.get("degree_as_awarded") or "")
        if not full or len(full) > TITLE_MAX["degree_as_awarded"] or abbreviated_degree(full):
            continue
        if fold(str(payload.get("institution_original") or "")) != fold(institution):
            continue
        year = str(payload.get("end_date") or "")[:4]
        if end_year is not None and year.isdigit() and int(year) != end_year:
            continue
        if _stems_in_order(stems, [w.casefold() for w in _LETTERS.findall(full)]):
            found.append(full)
    return found[0] if len(found) == 1 else None


def full_titles(
    content: CVContent, facts: Sequence[VerifiedFact], undone: frozenset[str]
) -> tuple[CVContent, tuple[AppliedFix, ...]]:
    """Replace an abbreviated degree title with the document's, and keep the
    replacement only when the verifier still reads that entry SUPPORTED or
    UNCERTAIN against `facts` (the verification set). Otherwise the title
    prints as written and the gap question (gaps.abbreviated_names) asks."""
    education: list[EducationEntry] = list(content.education)
    fixes: list[AppliedFix] = []
    for index, entry in enumerate(content.education):
        if not abbreviated_degree(entry.degree_as_awarded):
            continue
        end_year = entry.end_date.year if entry.end_date else None
        full = full_title_for(
            entry.degree_as_awarded, entry.institution_original, end_year, facts
        )
        if full is None:
            continue
        subject = subject_of(FULL_TITLE, entry.degree_as_awarded)
        was_undone = subject in undone
        if not was_undone:
            before_verdicts = verify_against_facts(
                content.model_copy(update={"education": tuple(education)}), facts
            )
            before_verdict = next(
                (v.verdict for v in before_verdicts if v.claim_path == f"education[{index}]"),
                None,
            )
            trial = [*education]
            trial[index] = entry.model_copy(update={"degree_as_awarded": full})
            verdicts = verify_against_facts(
                content.model_copy(update={"education": tuple(trial)}), facts
            )
            verdict = next(
                v.verdict for v in verdicts if v.claim_path == f"education[{index}]"
            )
            allowed_verdicts = (
                (Verdict.SUPPORTED,)
                if before_verdict == Verdict.SUPPORTED
                else (Verdict.SUPPORTED, Verdict.UNCERTAIN)
            )
            if verdict not in allowed_verdicts:
                continue
            education = trial
        fixes.append(
            AppliedFix(
                FULL_TITLE,
                subject,
                f"education[{index}]",
                entry.degree_as_awarded,
                full,
                undone=was_undone,
            )
        )
    return content.model_copy(update={"education": tuple(education)}), tuple(fixes)


@transaction.atomic
def keep_wording(*, student: Membership, original: str, changed: str) -> VerifiedFact | None:
    """Spec §5.5: the student's one tap makes a verb fix their own wording.

    A new EXPERIENCE fact supersedes the one current confirmed fact holding the
    line, with that line replaced (every occurrence of it) and every other
    bullet untouched; confirmed by the student, since the student tapped. The
    opening came from the fixed list and the rest is the student's line, so no
    model authored it. None when no single fact holds the line -- a stale page.
    The one-superseder index refuses a concurrent second tap.
    """
    owners = [
        fact
        for fact in generatable_facts(student).filter(category=_EXP)
        if isinstance((b := _payload(fact).get("bullets")), list) and original in b
    ]
    if len(owners) != 1:
        return None
    tip = owners[0]
    tip_bullets = _payload(tip).get("bullets")
    if not isinstance(tip_bullets, list):
        return None
    bullets = [changed if line == original else line for line in tip_bullets]
    row = VerifiedFact.objects.create(
        student=student,
        category=_EXP,
        payload={**_payload(tip), "bullets": bullets},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="cv-fix:S-026",
        confirmed_by=student,
        confirmed_at=timezone.now(),
        supersedes=tip,
        created_by=student,
    )
    record_event(actor=student, event="fact.cv_fix_kept", object_id=row.id)
    return row
