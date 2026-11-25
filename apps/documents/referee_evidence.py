"""Match a student's verified CV facts, transcript courses, publications, awards,
and GitHub/PDF readings to a specific referee.

Pure: takes a `Referee`, `VerifiedFact` rows (from `generatable_facts`), and
`UsableReading` items (from `usable_readings`), and returns the concrete pieces
of work the student and this referee did together. No database writes, no
network calls, and no model calls.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from anyascii import anyascii

from .cv_evidence import _meets_name_floor, _norm, _whole_word_match
from .evidence.readings import UsableReading
from .models import Referee, VerifiedFact

_HONORIFICS = frozenset(
    {
        "prof",
        "professor",
        "pr",
        "dr",
        "dra",
        "drs",
        "dott",
        "ssa",
        "doctor",
        "assoc",
        "associate",
        "asst",
        "assistant",
        "reader",
        "lecturer",
        "senior",
        "principal",
        "dean",
        "provost",
        "chancellor",
        "fellow",
        "univ",
        "priv",
        "doz",
        "pd",
        "doc",
        "docent",
        "dosent",
        "hab",
        "habil",
        "inz",
        "mgr",
        "acad",
        "academician",
        "akademik",
        "catedratico",
        "catedratica",
        "mr",
        "mrs",
        "ms",
        "mx",
        "mme",
        "mlle",
        "sir",
        "dame",
        "phd",
        "dphil",
        "md",
        "ing",
        "ir",
        "dipl",
        "mag",
        "msc",
        "bsc",
        "mba",
        "llb",
        "llm",
        "jd",
        "dsc",
        "drsc",
        "jr",
        "sr",
        "ii",
        "iii",
        "iv",
        "frs",
        "fba",
        "freng",
        "fieee",
        "frsc",
        "emeritus",
        "emerita",
    }
)
_SURNAME_PARTICLES = frozenset(
    {
        "van",
        "der",
        "den",
        "de",
        "del",
        "della",
        "di",
        "da",
        "do",
        "dos",
        "das",
        "du",
        "des",
        "la",
        "le",
        "von",
        "zu",
        "zum",
        "zur",
        "al",
        "el",
        "bin",
        "ibn",
        "abi",
        "abu",
        "ben",
        "st",
        "saint",
        "sainte",
    }
)
_PATRONYMIC_MARKERS = frozenset({"oglu", "qizi", "gizi", "ogly", "kyzy", "uulu"})
_SLAVIC_PATRONYMIC_RE = re.compile(
    r"^[a-z]{3,}(?:ovich|evich|ovych|evych|ovna|evna|ivna|ichna|inicna)$"
)
_AFFILIATION_TAIL_WORDS = frozenset(
    {
        "university",
        "universitat",
        "universite",
        "universidad",
        "universidade",
        "universita",
        "universiteit",
        "universitesi",
        "univerzita",
        "uniwersytet",
        "politecnico",
        "polytechnique",
        "hochschule",
        "institute",
        "institut",
        "instituto",
        "istituto",
        "laboratory",
        "lab",
        "department",
        "departement",
        "departamento",
        "dipartimento",
        "dept",
        "faculty",
        "fakultat",
        "faculte",
        "facultad",
        "fakultesi",
        "school",
        "college",
        "center",
        "centre",
        "centro",
        "academy",
        "hospital",
        "clinic",
        "corp",
        "corporation",
        "company",
        "inc",
        "ltd",
        "gmbh",
        "ag",
        "sa",
        "bv",
        "plc",
        "ojsc",
        "cjsc",
        "llc",
        "bank",
    }
)
_SUBUNIT_CLAUSE_WORDS = frozenset(
    {
        "department",
        "departement",
        "departamento",
        "dipartimento",
        "dept",
        "faculty",
        "fakultat",
        "faculte",
        "facultad",
        "fakultesi",
        "bolumu",
        "kafedra",
        "chair",
        "lehrstuhl",
        "laboratory",
        "lab",
        "division",
        "section",
        "group",
        "center",
        "centre",
        "centro",
        "campus",
    }
)
_INSTITUTION_WRAPPER_WORDS = frozenset(
    {
        "university",
        "universitat",
        "universite",
        "universidad",
        "universidade",
        "universita",
        "universiteit",
        "universitesi",
        "univerzita",
        "uniwersytet",
        "the",
        "and",
        "for",
        "of",
        "in",
        "at",
        "on",
        "to",
        "by",
        "de",
        "del",
        "della",
        "da",
        "do",
        "dos",
        "das",
        "di",
        "du",
        "des",
        "la",
        "le",
        "les",
        "el",
        "los",
        "las",
        "von",
        "zu",
        "zum",
        "zur",
        "fur",
        "fuer",
        "und",
        "et",
        "ve",
        "va",
        "ltd",
        "inc",
        "corp",
        "corporation",
        "company",
        "llc",
        "gmbh",
        "ag",
        "sa",
        "bv",
        "plc",
        "ojsc",
        "cjsc",
    }
)
_ACRONYM_STOPWORDS = frozenset(
    {
        "and",
        "the",
        "for",
        "of",
        "in",
        "at",
        "de",
        "del",
        "da",
        "do",
        "dos",
        "di",
        "du",
        "des",
        "la",
        "le",
        "el",
        "von",
        "zu",
        "fur",
        "fuer",
        "und",
        "et",
        "ve",
    }
)
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_TOKEN_WITH_HYPHEN_RE = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)
_COURSE_CODE_RE = re.compile(r"\b[a-zA-Z]{2,5}[- ]?\d{3,4}[a-zA-Z]?\b")
_PAREN_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_ROLE_PREFIX_RE = re.compile(
    r"^\s*(?:(?:co-?)?supervis(?:ed\s+by|or)\s*:?|advis(?:ed\s+by|or)\s*:?|"
    r"mentor\s*:?|pi\s*:?|instructor\s*:?|lecturer\s*:?|taught\s+by\s*:?|"
    r"under\s+the\s+supervision\s+of\s*:?|chair\s*:?|"
    r"(?:tez\s+)?dan[ıi][şs]man[ıi]?\s*:?|elmi\s+r[əe]hb[əe]r[i]?\s*:?|"
    r"r[əe]hb[əe]r\s*:?|научный\s+руководитель\s*:?|руководитель\s*:?|"
    r"преподаватель\s*:?|лектор\s*:?|betreuer(?:in)?\s*:?|"
    r"direct(?:eur|rice)(?:\s+de\s+(?:th[èe]se|m[ée]moire|recherche))?\s*:?|"
    r"encadrant(?:e)?\s*:?|relatore\s*:?|tutor(?:a)?\s*:?)\s*",
    re.IGNORECASE,
)
_PEOPLE_SPLIT_RE = re.compile(
    r"\s*(?:;|/|&|\+|\b(?:and|und|et|en|ve|və|with|mit|avec|con)\b)\s*",
    re.IGNORECASE,
)
_COURSE_STOPWORDS = frozenset(
    {
        "and",
        "or",
        "the",
        "of",
        "in",
        "to",
        "for",
        "with",
        "on",
        "at",
        "by",
        "from",
        "my",
        "our",
        "course",
        "courses",
        "class",
        "classes",
        "grade",
        "grades",
        "project",
        "projects",
        "thesis",
        "supervised",
        "taught",
        "professor",
        "prof",
        "dr",
        "introduction",
        "intro",
        "advanced",
        "applied",
        "fundamentals",
        "principles",
        "einfuhrung",
        "einführung",
        "vorlesung",
        "praktikum",
        "ubung",
        "übung",
        "seminaire",
        "séminaire",
        "cours",
        "введение",
        "vvedenie",
        "лекция",
        "lektsiya",
        "практикум",
        "семинар",
        "seminar",
        "giris",
        "giriş",
        "girish",
        "ders",
        "dersi",
        "temel",
        "fənn",
        "fann",
        "mühazirə",
        "muhazira",
    }
)
_AZ_CHAR_MAP = str.maketrans(
    {
        "ə": "a",
        "Ə": "a",
        "ş": "sh",
        "Ş": "sh",
        "ç": "ch",
        "Ç": "ch",
        "ğ": "gh",
        "Ğ": "gh",
        "ı": "i",
        "İ": "i",
        "ö": "o",
        "Ö": "o",
        "ü": "u",
        "Ü": "u",
    }
)
_DIGRAPHS = (("ae", "a"), ("oe", "o"), ("ue", "u"))


@dataclass(frozen=True)
class SharedWorkItem:
    #: "research", "experience", "publication", "github", "pdf", "coursework", "education", "award"
    kind: str
    #: One-line factual description ready for the referee sheet and email.
    summary: str
    #: Supporting verified or Jev-supported bullets (max 3 per item).
    bullets: tuple[str, ...] = ()


def _fold_ascii(text: str) -> str:
    folded = anyascii(text).casefold()
    for digraph, vowel in _DIGRAPHS:
        folded = folded.replace(digraph, vowel)
    return re.sub(r"[^a-z]", "", folded)


def _skeleton(ascii_word: str) -> str:
    s = ascii_word
    for src, dst in (
        ("szcz", "sc"),
        ("shch", "sc"),
        ("sch", "s"),
        ("tch", "c"),
        ("dzh", "j"),
        ("dsh", "j"),
        ("sh", "s"),
        ("ch", "c"),
        ("sz", "s"),
        ("cz", "c"),
        ("rz", "z"),
        ("gh", "g"),
        ("kh", "x"),
        ("zh", "z"),
        ("ph", "f"),
        ("th", "t"),
        ("tz", "z"),
        ("ts", "s"),
        ("dj", "j"),
        ("ou", "u"),
        ("oo", "u"),
        ("ee", "i"),
        ("ey", "ai"),
        ("ei", "ai"),
        ("ay", "ai"),
        ("iy", "i"),
        ("yi", "i"),
        ("ii", "i"),
        ("ia", "ya"),
        ("iu", "yu"),
        ("io", "yo"),
    ):
        s = s.replace(src, dst)
    if s.startswith("q"):
        s = "g" + s[1:]
    if s in {"zadeh", "zade"}:
        s = "zada"
    for suffix, repl in (
        ("skyi", "ski"),
        ("skiy", "ski"),
        ("skii", "ski"),
        ("sky", "ski"),
        ("yev", "ev"),
        ("iev", "ev"),
        ("yeva", "eva"),
        ("ieva", "eva"),
        ("yuk", "uk"),
        ("iuk", "uk"),
        ("zadeh", "zada"),
        ("zade", "zada"),
    ):
        if s.endswith(suffix) and len(s) > len(suffix) + 1:
            s = s[: -len(suffix)] + repl
            break
    # Collapse doubled consonants (e.g. "mohammed" -> "mohamed", "hassan" -> "hasan")
    s = re.sub(r"([bcdfghjklmnpqrstvwxz])\1+", r"\1", s)
    return s


def _token_forms(raw_word: str) -> frozenset[str]:
    """Return normalized transliteration forms for a single name word."""
    low = raw_word.strip().casefold()
    if not low:
        return frozenset()
    az_mapped = _fold_ascii(low.translate(_AZ_CHAR_MAP))
    plain_ascii = _fold_ascii(low)
    forms = {f for f in (az_mapped, plain_ascii) if f}
    for base in list(forms):
        skel = _skeleton(base)
        if skel:
            forms.add(skel)
        if base.endswith(("ov", "ova", "ev", "eva", "zada", "zade")) and "e" in base:
            harmonized = base.replace("e", "a")
            forms.add(harmonized)
            forms.add(_skeleton(harmonized))
        # Normalize common Arabic/Persian/South Asian vowel transliteration pairs
        # (e.g. Muhammad/Mohammad/Mohammed/Mohamed, Ahmad/Ahmed, Husain/Hussain/Hussein)
        if len(skel) >= 5 and skel.startswith(
            ("mham", "moham", "muham", "ahm", "hus", "hos", "sul", "yus", "yos")
        ):
            vowel_norm = re.sub(r"[aeiouy]+", "a", skel)
            forms.add(vowel_norm)
    return frozenset(f for f in forms if f)


def _tokens_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return bool(_token_forms(a) & _token_forms(b))


def _initial_matches(initial_token: str, full_token: str) -> bool:
    init_forms = _token_forms(initial_token)
    full_forms = _token_forms(full_token)
    if not any(len(f) == 1 for f in init_forms):
        return False
    return any(
        ff.startswith(inf)
        for inf in init_forms
        if len(inf) <= 2
        for ff in full_forms
        if len(ff) >= 2
    )


def _is_affiliation_tail(segment: str) -> bool:
    words = [_fold_ascii(w) for w in _WORD_RE.findall(segment)]
    words = [w for w in words if w]
    if not words:
        return False
    if any(w in _AFFILIATION_TAIL_WORDS for w in words):
        return True
    raw_words = _WORD_RE.findall(segment.strip())
    return len(raw_words) == 1 and raw_words[0].isupper() and 3 <= len(raw_words[0]) <= 8


def _looks_like_person_segment(segment: str) -> bool:
    raw_words = [_fold_ascii(w) for w in _WORD_RE.findall(segment)]
    words = [w for w in raw_words if w]
    if not words:
        return False
    if words[0] in _HONORIFICS:
        return len(words) >= 2
    meaningful = [w for w in words if w not in _HONORIFICS]
    return len(meaningful) >= 2


def _split_people(raw: str) -> tuple[str, ...]:
    """Split a supervisor/author string into individual person segments."""
    cleaned = _PAREN_RE.sub(" ", raw)
    cleaned = _ROLE_PREFIX_RE.sub("", cleaned).strip()
    if not cleaned:
        return ()
    chunks = [c.strip() for c in _PEOPLE_SPLIT_RE.split(cleaned) if c.strip()]
    people: list[str] = []
    for chunk in chunks:
        if " - " in chunk:
            left, _, right = chunk.partition(" - ")
            if _is_affiliation_tail(right):
                chunk = left.strip()
        if "," in chunk:
            comma_parts = [p.strip() for p in chunk.split(",") if p.strip()]
            if len(comma_parts) == 2 and _is_affiliation_tail(comma_parts[1]):
                people.append(comma_parts[0])
                continue
            if len(comma_parts) >= 2 and all(
                _looks_like_person_segment(p) for p in comma_parts
            ):
                people.extend(comma_parts)
                continue
        if chunk:
            people.append(chunk)
    return tuple(people)


def _clean_word_list(raw_part: str) -> list[str]:
    tokens: list[str] = []
    for tok in _TOKEN_WITH_HYPHEN_RE.findall(raw_part):
        folded = _fold_ascii(tok)
        if not folded or folded in _HONORIFICS:
            continue
        if "-" in tok and all(_fold_ascii(p) in _HONORIFICS for p in tok.split("-") if p):
            continue
        tokens.append(tok.casefold())
    # Strip Turkic patronymic marker ("oğlu", "qızı", "uulu", "kyzy") and its preceding
    # patronymic given name when at least two other name tokens remain.
    cleaned: list[str] = []
    for tok in tokens:
        if _fold_ascii(tok) in _PATRONYMIC_MARKERS:
            if len(cleaned) >= 2:
                cleaned.pop()
            continue
        cleaned.append(tok)
    # Strip Slavic patronymic token ("Ivanovich", "Petrivna", etc.) when >= 3 tokens exist
    if len(cleaned) >= 3:
        without_slavic = [
            t for t in cleaned if not _SLAVIC_PATRONYMIC_RE.match(_fold_ascii(t))
        ]
        if len(without_slavic) >= 2:
            cleaned = without_slavic
    return cleaned


def _strip_prefix_particles(words: Sequence[str]) -> list[str]:
    """Strip nobiliary particles (`van`, `de`, `le`, `du`, `al`, etc.) ONLY when they
    precede a subsequent surname token—preserving short surnames like `Prof. Minh Le`,
    `Prof. Subhashis De`, `Prof. Bowen Du`, or `Prof. Quang Do`."""
    if len(words) <= 1:
        return list(words)
    non_particles = [w for w in words[:-1] if _fold_ascii(w) not in _SURNAME_PARTICLES]
    return [*non_particles, words[-1]]


def _strip_trailing_particles(words: Sequence[str]) -> list[str]:
    """Strip particles from the given-name side of a comma-inverted name (`Waals, J. van der`)."""
    return [w for w in words if _fold_ascii(w) not in _SURNAME_PARTICLES]


def _name_tokens(raw: str) -> tuple[tuple[str, ...], str]:
    """Return `(given_tokens, surname)` in casefolded form, stripping honorifics and
    prefix particles.

    Handles:
    - `"Prof. Philippe Schwaller"` -> `(("philippe",), "schwaller")`
    - `"Schwaller, P."` -> `(("p",), "schwaller")`
    - `"Prof. van der Waals"` -> `((), "waals")`
    - `"Waals, J. van der"` -> `(("j",), "waals")`
    - `"Prof. Minh Le"` -> `(("minh",), "le")`
    - `"Aliyev R. M."` -> `(("r", "m"), "aliyev")`
    """
    people = _split_people(raw)
    text = people[0] if people else _PAREN_RE.sub(" ", raw).strip()
    if not text:
        return (), ""
    if "," in text:
        surname_part, _, rest_part = text.partition(",")
        surname_words = _strip_prefix_particles(_clean_word_list(surname_part))
        given_words: list[str] = []
        for g_tok in _strip_trailing_particles(_clean_word_list(rest_part)):
            given_words.extend(part for part in g_tok.split("-") if part)
        if surname_words:
            if len(surname_words) >= 2:
                # Preserve primary compound surname tokens (e.g. "García López, Carlos")
                return tuple([*given_words, *surname_words[:-1]]), surname_words[-1]
            return tuple(given_words), surname_words[-1]
    raw_words = _strip_prefix_particles(_clean_word_list(text))
    if not raw_words:
        return (), ""
    if len(raw_words) == 1:
        return (), raw_words[0]
    # Detect surname-first with trailing initials (e.g. "Aliyev R." or "Ivanov S. I.")
    if (
        len(_fold_ascii(raw_words[0])) >= 2
        and all(len(_fold_ascii(w)) == 1 for w in raw_words[1:])
    ):
        return tuple(raw_words[1:]), raw_words[0]
    given_expanded: list[str] = []
    for g_tok in raw_words[:-1]:
        given_expanded.extend(part for part in g_tok.split("-") if part)
    return tuple(given_expanded), raw_words[-1]


def _surname_matches(
    ref_surname: str,
    cand_surname: str,
    ref_given: tuple[str, ...],
    cand_given: tuple[str, ...],
) -> bool:
    if len(_fold_ascii(ref_surname)) < 2 or len(_fold_ascii(cand_surname)) < 2:
        return False
    if _tokens_match(ref_surname, cand_surname):
        return True
    # Hyphenated compound surname (e.g. "garcia-lopez" vs "garcia lopez" or "garcia" or "lopez")
    for hyp, other, other_given in (
        (ref_surname, cand_surname, cand_given),
        (cand_surname, ref_surname, ref_given),
    ):
        if "-" in hyp:
            parts = [p for p in hyp.split("-") if p]
            if len(parts) >= 2 and (
                _tokens_match(parts[-1], other) or _tokens_match(parts[0], other)
            ):
                if (
                    not other_given
                    or _tokens_match(parts[0], other_given[-1])
                    or len(other_given) >= 1
                ):
                    return True
    # Unhyphenated Hispanic/Portuguese dual surname (e.g. "Carlos García López" vs "Carlos García")
    for longer_given, other_surname, other_given in (
        (ref_given, cand_surname, cand_given),
        (cand_given, ref_surname, ref_given),
    ):
        if (
            len(longer_given) >= 2
            and len(other_given) >= 1
            and _tokens_match(longer_given[-1], other_surname)
        ):
            return True
    return False


def _given_compatible(ref_given: tuple[str, ...], cand_given: tuple[str, ...]) -> bool:
    if not ref_given or not cand_given:
        return True
    r0, c0 = ref_given[0], cand_given[0]
    if _tokens_match(r0, c0):
        return True
    if _initial_matches(r0, c0) or _initial_matches(c0, r0):
        return True
    # Multi-initial token (e.g. "JP" matching ("jean", "pierre"))
    for short_tok, multi_tokens in ((c0, ref_given), (r0, cand_given)):
        folded_short = _fold_ascii(short_tok)
        if 2 <= len(folded_short) == len(multi_tokens) <= 3 and all(
            len(_fold_ascii(t)) >= 2 for t in multi_tokens
        ):
            initials = "".join(_fold_ascii(t)[0] for t in multi_tokens)
            if folded_short == initials:
                return True
    return False


def _flat_name_parts(given: tuple[str, ...], surname: str) -> tuple[str, ...]:
    parts: list[str] = []
    for g in given:
        parts.extend(p for p in g.split("-") if p)
    parts.extend(p for p in surname.split("-") if p)
    return tuple(parts)


def _single_person_matches(referee_name: str, candidate_name: str) -> bool:
    ref_given, ref_surname = _name_tokens(referee_name)
    cand_given, cand_surname = _name_tokens(candidate_name)
    if not ref_surname or not cand_surname:
        return False
    if _surname_matches(ref_surname, cand_surname, ref_given, cand_given):
        if _given_compatible(ref_given, cand_given):
            return True
    # Family-name-first rotation without comma (e.g. East Asian "Zhang Wei" vs "Wei Zhang",
    # "Kim Min-jun" vs "Min-jun Kim", Hungarian "Kovács János" vs "János Kovács",
    # or Slavic/Turkic "Aliyev Rauf" vs "Rauf Aliyev").
    ref_flat = _flat_name_parts(ref_given, ref_surname)
    cand_flat = _flat_name_parts(cand_given, cand_surname)
    if (
        2 <= len(ref_flat) == len(cand_flat) <= 4
        and all(len(_fold_ascii(t)) >= 2 for t in (*ref_flat, *cand_flat))
    ):
        ref_rot = (*ref_flat[1:], ref_flat[0])
        cand_rot = (*cand_flat[1:], cand_flat[0])
        if all(_tokens_match(a, b) for a, b in zip(ref_rot, cand_flat, strict=True)) or all(
            _tokens_match(a, b) for a, b in zip(cand_rot, ref_flat, strict=True)
        ):
            return True
    return False


def person_matches(referee_name: str, candidate_name: str) -> bool:
    """True when `candidate_name` (including a co-supervisor list) names `referee_name`.

    Handles international honorifics, prefix particles (`van der`, `von`, `al`), short
    Asian/Indian surnames (`Le`, `De`, `Du`, `Do`), Turkic & Slavic patronymics (`oğlu`,
    `Ivanovich`, `Petrivna`), diacritics/umlauts/transliterations (`Əliyev` ↔ `Aliyev`,
    `Müller` ↔ `Mueller`, `Mohammed` ↔ `Muhammad`, `Kovalskyi` ↔ `Kovalsky`),
    Hispanic/Portuguese compound surnames (`García López` ↔ `García-López` ↔ `García`),
    concatenated initials (`JP Sauvage`), and family-name-first order (`Kim Min-jun` ↔
    `Min-jun Kim`, `Zhang Wei` ↔ `Wei Zhang`, `Kovács János` ↔ `János Kovács`).
    """
    if not referee_name.strip() or not candidate_name.strip():
        return False
    segments = _split_people(candidate_name)
    if not segments:
        return False
    return any(_single_person_matches(referee_name, seg) for seg in segments)


def group_matches(referee_name: str, text: str) -> bool:
    """True when `text` names the referee's lab, research group, or GitHub org.

    Matches `"Prof. Philippe Schwaller's group"`, `"Schwaller Lab"`, and GitHub
    owners like `"schwallergroup"` or `"schwaller-lab"` across transliterations.
    """
    _, surname = _name_tokens(referee_name)
    surname_forms = {f for f in _token_forms(surname) if len(f) >= 3}
    if not surname_forms or not text.strip():
        return False
    text_words = _WORD_RE.findall(text)
    for w in text_words:
        if _token_forms(w) & surname_forms:
            return True
    collapsed_forms = {
        "".join(_fold_ascii(w) for w in text_words),
        "".join(_skeleton(_fold_ascii(w)) for w in text_words),
    }
    for s_form in surname_forms:
        for suffix in ("group", "lab", "laboratory", "team", "research", "chair"):
            target = f"{s_form}{suffix}"
            if any(target in c for c in collapsed_forms):
                return True
    return False


def _strip_institution_subunits(raw: str) -> str:
    """Strip trailing department/faculty/lab clauses while keeping the main institution name."""
    no_parens = _PAREN_RE.sub(" ", raw)
    clauses = [c.strip() for c in re.split(r"[,;/]|\s+[-–—]\s+", no_parens) if c.strip()]
    if len(clauses) <= 1:
        return no_parens.strip()
    kept = [clauses[0]]
    for clause in clauses[1:]:
        clause_words = {_fold_ascii(w) for w in _WORD_RE.findall(clause) if _fold_ascii(w)}
        if clause_words & _SUBUNIT_CLAUSE_WORDS:
            continue
        kept.append(clause)
    return " ".join(kept)


def _institution_signature(raw: str) -> tuple[frozenset[str], frozenset[str]]:
    """Return `(core_tokens, acronyms)` for an institution or employer name."""
    all_raw_words = _WORD_RE.findall(raw)
    all_folded = [_fold_ascii(w) for w in all_raw_words if _fold_ascii(w)]
    acronyms: set[str] = set()
    for raw_w in all_raw_words:
        folded_w = _fold_ascii(raw_w)
        if 3 <= len(folded_w) <= 6 and (raw_w.isupper() or len(all_folded) == 1):
            acronyms.add(folded_w)

    core_text = _strip_institution_subunits(raw)
    core_words = [_fold_ascii(w) for w in _WORD_RE.findall(core_text) if _fold_ascii(w)]
    if not core_words:
        core_words = all_folded

    sig_words = [w for w in core_words if len(w) >= 3 and w not in _ACRONYM_STOPWORDS]
    if len(sig_words) >= 3:
        acronyms.add("".join(w[0] for w in sig_words))

    core_tokens = frozenset(
        w for w in core_words if len(w) >= 3 and w not in _INSTITUTION_WRAPPER_WORDS
    )
    return core_tokens, frozenset(acronyms)


def institution_matches(referee_institution: str, candidate_institution: str) -> bool:
    """True when `referee_institution` and `candidate_institution` refer to the same body."""
    if not referee_institution.strip() or not candidate_institution.strip():
        return False
    ref_norm = _norm(referee_institution)
    cand_norm = _norm(candidate_institution)
    if ref_norm and ref_norm == cand_norm:
        return True
    ref_core, ref_acr = _institution_signature(referee_institution)
    cand_core, cand_acr = _institution_signature(candidate_institution)
    if ref_core and cand_core and ref_core == cand_core:
        return True
    if ref_acr & cand_acr:
        return True
    if (len(ref_core) == 1 and (ref_core & cand_acr)) or (
        len(cand_core) == 1 and (cand_core & ref_acr)
    ):
        return True
    return False


def extract_supervisor_name_and_title(raw: str) -> tuple[str, str]:
    """Extract `(honorific_title, clean_name)` from a raw supervisor string."""
    people = _split_people(raw)
    first = people[0] if people else _PAREN_RE.sub(" ", raw).strip()
    if not first:
        return "", ""
    tokens = first.split()
    title_parts: list[str] = []
    name_parts: list[str] = []
    in_title = True
    for tok in tokens:
        folded = _fold_ascii(tok)
        if in_title and folded in _HONORIFICS:
            title_parts.append(tok if tok.endswith(".") else tok)
        else:
            in_title = False
            name_parts.append(tok.rstrip(","))
    return " ".join(title_parts)[:60], " ".join(name_parts)[:200]


def _date_span(payload: dict[str, Any]) -> str:
    parts = [str(d) for d in (payload.get("start_date"), payload.get("end_date")) if d]
    return "–".join(parts)


def _relationship_mentions(relationship: str, candidate_title: str) -> bool:
    """True when the student's `Referee.relationship` note names `candidate_title`."""
    if not relationship.strip() or not candidate_title.strip():
        return False
    if _whole_word_match(candidate_title, relationship):
        return True
    rel_norm = _norm(relationship)
    cand_norm = _norm(candidate_title)
    return bool(cand_norm and len(cand_norm) >= 6 and cand_norm in rel_norm)


def _word_stem_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) >= 5 and (a.startswith(b[:5]) or b.startswith(a[:5])):
        return abs(len(a) - len(b)) <= 3
    return False


def _course_matches_relationship(course_title: str, relationship: str) -> bool:
    if not course_title.strip() or not relationship.strip():
        return False
    # 1. Alphanumeric course codes (e.g. CS224N, MATH101, INF-204)
    course_codes = {
        re.sub(r"[\s-]+", "", m.group(0)).casefold()
        for m in _COURSE_CODE_RE.finditer(course_title)
    }
    rel_codes = {
        re.sub(r"[\s-]+", "", m.group(0)).casefold()
        for m in _COURSE_CODE_RE.finditer(relationship)
    }
    if course_codes and (course_codes & rel_codes):
        return True

    # 2. Short uppercase subject acronyms (e.g. NLP, ML, AI, OS, DB, HPC, LLM)
    course_acronyms = {
        w.casefold()
        for w in _WORD_RE.findall(course_title)
        if 2 <= len(w) <= 3 and w.isupper() and w.casefold() not in _COURSE_STOPWORDS
    }
    rel_words_all = {_fold_ascii(w) for w in _WORD_RE.findall(relationship) if _fold_ascii(w)}
    if course_acronyms & rel_words_all:
        return True

    # 3. Content words >= 4 chars with stem/plural tolerance
    course_words = [
        _fold_ascii(w)
        for w in _WORD_RE.findall(course_title)
        if len(_fold_ascii(w)) >= 4
        and _fold_ascii(w) not in _COURSE_STOPWORDS
        and w.casefold() not in _COURSE_STOPWORDS
    ]
    if not course_words:
        return False
    return any(
        _word_stem_match(cw, rw)
        for cw in course_words
        for rw in rel_words_all
        if len(rw) >= 4
    )


def _supported_reading_bullets(reading: UsableReading) -> tuple[str, ...]:
    return tuple(
        b.text.strip()
        for b in reading.bullets
        if b.verdict == "supported" and b.text.strip()
    )[:3]


_RESEARCH_ROLE_MARKERS = (
    "thesis",
    "dissertation",
    "research",
    "supervis",
    "paper",
    "co-author",
    "tez",
    "bitirme",
    "danışman",
    "danisman",
    "araştırma",
    "arastirma",
    "laboratuvar",
    "diplom işi",
    "diplom isi",
    "buraxılış işi",
    "buraxilis isi",
    "elmi rəhbər",
    "elmi rehber",
    "tədqiqat",
    "tedqiqat",
    "научный руководитель",
    "диплом",
    "диссертац",
    "исследован",
    "лаборатор",
    "bachelorarbeit",
    "masterarbeit",
    "abschlussarbeit",
    "betreuer",
    "forschung",
    "mémoire",
    "memoire",
    "thèse",
    "these",
    "directeur",
    "encadrant",
    "recherche",
    "tesis",
    "tesi",
    "relatore",
)
_TEACHING_ROLE_MARKERS = (
    "taught",
    "course",
    "lecture",
    "class",
    "seminar",
    "instructor",
    "module",
    "practicum",
    "ders",
    "hoca",
    "müəllim",
    "muellim",
    "преподаватель",
    "лектор",
    "курс",
    "vorlesung",
    "cours",
    "tutor",
)
_PROFESSIONAL_ROLE_MARKERS = (
    "staj",
    "müdür",
    "mudur",
    "təcrübə",
    "tecrube",
    "стажировк",
    "praktikum",
    "stage",
)


def referee_angle(referee: Referee, shared_work: Sequence[SharedWorkItem]) -> str:
    """Return a concise recommendation focus for `referee` based on verified shared work."""
    kinds = {item.kind for item in shared_work}
    if "research" in kinds and "publication" in kinds:
        return "Research supervision, co-authored publication, and independent inquiry"
    if "publication" in kinds:
        return "Co-authored research output and scholarly contribution"
    if "research" in kinds or "pdf" in kinds or "github" in kinds:
        return "Research supervision, technical methods, and project execution"
    if "coursework" in kinds:
        return "Classroom performance, analytical rigour, and subject mastery"
    if "experience" in kinds and referee.kind == Referee.Kind.PROFESSIONAL:
        return "Workplace performance, delivery under responsibility, and professional impact"
    if "experience" in kinds:
        return "Practical project execution and research-group contribution"
    if referee.kind == Referee.Kind.PROFESSIONAL:
        return "Professional capability, leadership, and workplace contribution"
    rel_low = referee.relationship.casefold().replace("i̇", "i")
    if any(m in rel_low for m in _RESEARCH_ROLE_MARKERS):
        return "Research supervision, technical methods, and project execution"
    if any(m in rel_low for m in _TEACHING_ROLE_MARKERS):
        return "Classroom performance, analytical rigour, and subject mastery"
    if any(m in rel_low for m in _PROFESSIONAL_ROLE_MARKERS):
        return "Workplace performance, delivery under responsibility, and professional impact"
    return "Academic preparation and readiness for graduate study"


def shared_work_for_referee(
    referee: Referee,
    *,
    facts: Iterable[VerifiedFact],
    readings: Sequence[UsableReading] = (),
) -> tuple[SharedWorkItem, ...]:
    """Return every verified piece of work linking the student to `referee`.

    Checks seven sources in order:
    1. Supervised theses / research (`EDUCATION.supervisor` and `RESEARCH.supervisor`,
       or a thesis named in `referee.relationship`).
    2. Academic, lab, or professional posts (`EXPERIENCE.supervisor`, `EXPERIENCE.group`,
       `EXPERIENCE.employer` matching `referee.institution`, or a project/role named in
       `referee.relationship`).
    3. Co-authored publications and conference talks (`PUBLICATION.authors`).
    4. Checked GitHub repositories (`source="github"`) and uploaded thesis/report PDFs
       (`source="pdf"`) from `usable_readings` linked either directly to the referee's
       lab/org or transitively to a matched thesis/experience/project entry.
    5. Checked transcript courses (`EDUCATION.courses`, never `courses_unconfirmed`)
       named in `referee.relationship`.
    6. Honours / awards (`AWARD`) naming the referee, a matched thesis/project, or
       `referee.relationship`.
    7. Institution-matched degree context (`EDUCATION`) when `referee.institution` matches
       the student's university and no specific thesis from that degree was already added.
    """
    fact_list = list(facts)
    items: list[SharedWorkItem] = []
    seen_summaries: set[str] = set()
    matched_titles: list[str] = []
    matched_groups: list[str] = []
    matched_edu_fact_ids: set[Any] = set()

    def _add(kind: str, summary: str, bullets: Iterable[str] = ()) -> None:
        clean_summary = summary.strip()
        key = _norm(clean_summary)
        if not clean_summary or not key or key in seen_summaries:
            return
        seen_summaries.add(key)
        clean_bullets = tuple(dict.fromkeys(b.strip() for b in bullets if b and b.strip()))[:3]
        items.append(SharedWorkItem(kind=kind, summary=clean_summary, bullets=clean_bullets))

    # 1. Research entries & supervised degree theses
    seen_theses: set[str] = set()
    for fact in fact_list:
        if fact.category != VerifiedFact.Category.RESEARCH or not isinstance(fact.payload, dict):
            continue
        p = fact.payload
        supervisor = str(p.get("supervisor") or "")
        thesis = str(p.get("thesis_title") or "")
        institution = str(p.get("institution") or "")
        if not (
            person_matches(referee.name, supervisor)
            or group_matches(referee.name, supervisor)
            or _relationship_mentions(referee.relationship, thesis)
        ):
            continue
        if thesis:
            seen_theses.add(_norm(thesis))
            matched_titles.append(thesis)
        parts = [
            f"Research / thesis: {thesis}" if thesis else "Supervised research",
            institution,
            _date_span(p),
        ]
        bullets: list[str] = []
        if p.get("methods"):
            bullets.append(f"Methods: {p['methods']}")
        if p.get("outcomes"):
            bullets.append(f"Outcomes: {p['outcomes']}")
        _add("research", ", ".join(part for part in parts if part), bullets)

    for fact in fact_list:
        if fact.category != VerifiedFact.Category.EDUCATION or not isinstance(fact.payload, dict):
            continue
        p = fact.payload
        supervisor = str(p.get("supervisor") or "")
        thesis = str(p.get("thesis_title") or "")
        degree = str(p.get("degree_english") or p.get("degree_as_awarded") or "")
        institution = str(p.get("institution_english") or p.get("institution_original") or "")
        if (
            person_matches(referee.name, supervisor)
            or group_matches(referee.name, supervisor)
            or (thesis and _relationship_mentions(referee.relationship, thesis))
        ):
            matched_edu_fact_ids.add(fact.id)
            if thesis and _norm(thesis) not in seen_theses:
                seen_theses.add(_norm(thesis))
                matched_titles.append(thesis)
                parts = [
                    f"Thesis ({degree}): {thesis}" if degree else f"Thesis: {thesis}",
                    institution,
                    f"grade {p['grade_native']}" if p.get("grade_native") else "",
                ]
                _add("research", ", ".join(part for part in parts if part))
            elif not thesis and degree:
                parts = [
                    f"Supervised degree: {degree}",
                    institution,
                    f"grade {p['grade_native']}" if p.get("grade_native") else "",
                ]
                _add("research", ", ".join(part for part in parts if part))

    # 2. Experience entries (academic / lab / RA / TA / professional employer posts)
    for fact in fact_list:
        if fact.category != VerifiedFact.Category.EXPERIENCE or not isinstance(fact.payload, dict):
            continue
        p = fact.payload
        supervisor = str(p.get("supervisor") or "")
        group = str(p.get("group") or "")
        project = str(p.get("project") or "")
        title = str(p.get("title") or "")
        employer = str(p.get("employer") or "")
        employer_match = bool(
            referee.institution and employer and institution_matches(referee.institution, employer)
        )
        if not (
            person_matches(referee.name, supervisor)
            or group_matches(referee.name, supervisor)
            or group_matches(referee.name, group)
            or (project and _relationship_mentions(referee.relationship, project))
            or (title and _relationship_mentions(referee.relationship, title))
            or employer_match
        ):
            continue
        if project:
            matched_titles.append(project)
        if title:
            matched_titles.append(title)
        if group:
            matched_groups.append(group)
        raw_bullets = p.get("bullets")
        exp_bullets = (
            [str(b) for b in raw_bullets if isinstance(b, str) and b.strip()]
            if isinstance(raw_bullets, list | tuple)
            else []
        )
        parts = [
            f"{title} ({project})" if project and title else (title or project),
            group or employer,
            employer if group and employer and employer.casefold() not in group.casefold() else "",
            _date_span(p),
        ]
        _add("experience", ", ".join(part for part in parts if part), exp_bullets)

    # 3. Co-authored publications & conference presentations (CV / Crossref / OpenAlex)
    for fact in fact_list:
        if (
            fact.category != VerifiedFact.Category.PUBLICATION
            or not isinstance(fact.payload, dict)
        ):
            continue
        p = fact.payload
        raw_authors = p.get("authors")
        authors = (
            [str(a) for a in raw_authors if isinstance(a, str)]
            if isinstance(raw_authors, list | tuple)
            else []
        )
        pub_title = str(p.get("title") or "")
        if not (
            any(person_matches(referee.name, author) for author in authors)
            or (pub_title and _relationship_mentions(referee.relationship, pub_title))
        ):
            continue
        if pub_title:
            matched_titles.append(pub_title)
        venue = str(p.get("venue") or "")
        year = str(p.get("year") or "")
        doi = str(p.get("doi") or "")
        kind_label = "Co-authored presentation" if p.get("is_presentation") else "Co-authored paper"
        parts = [
            f"{kind_label}: {pub_title}" if pub_title else kind_label,
            venue,
            year,
            f"doi:{doi}" if doi else "",
        ]
        _add("publication", ", ".join(part for part in parts if part))

    # 4. Checked GitHub repositories & uploaded thesis/report PDFs (usable_readings)
    norm_matched_titles = {_norm(t) for t in matched_titles if _norm(t)}
    qualifying_matched_titles = [t for t in matched_titles if _meets_name_floor(t)]

    for reading in readings:
        owner_login = reading.repo.split("/", 1)[0] if "/" in reading.repo else ""
        repo_short = reading.repo.split("/", 1)[1] if "/" in reading.repo else reading.repo
        direct_org_match = reading.source == "github" and (
            group_matches(referee.name, reading.owner_name)
            or group_matches(referee.name, owner_login)
            or (
                bool(referee.institution)
                and bool(reading.owner_name)
                and institution_matches(referee.institution, reading.owner_name)
            )
            or any(
                _whole_word_match(org, group)
                for org in (reading.owner_name, owner_login)
                if org
                for group in matched_groups
            )
        )
        reading_names = [n for n in (*reading.names, repo_short) if n]
        transitive_title_match = any(
            _norm(n) in norm_matched_titles
            for n in reading.names
            if _norm(n)
        ) or any(
            _whole_word_match(name, f"{reading.summary} {' '.join(reading.names)}")
            for name in qualifying_matched_titles
        )
        relationship_match = any(
            _relationship_mentions(referee.relationship, n) for n in reading_names
        )
        if not (direct_org_match or transitive_title_match or relationship_match):
            continue

        r_bullets = list(_supported_reading_bullets(reading))
        if reading.source == "github":
            commit_note = f"{reading.commits} commits" if reading.commits > 0 else ""
            label = reading.repo or (reading.names[0] if reading.names else "repository")
            parts = [
                f"GitHub repository: {label}",
                commit_note,
                reading.summary,
            ]
            _add("github", " — ".join(part for part in parts if part), r_bullets)
        else:
            title_label = reading.names[0] if reading.names else reading.summary
            parts = [
                f"Thesis/report PDF: {title_label}" if title_label else "Thesis/report PDF",
                reading.summary if reading.summary and reading.summary != title_label else "",
            ]
            if reading.methods:
                r_bullets.append(f"Methods: {reading.methods}")
            if reading.outcomes:
                r_bullets.append(f"Outcomes: {reading.outcomes}")
            _add("pdf", " — ".join(part for part in parts if part), r_bullets)

    # 5. Checked transcript courses on EDUCATION facts (never courses_unconfirmed)
    for fact in fact_list:
        if fact.category != VerifiedFact.Category.EDUCATION or not isinstance(fact.payload, dict):
            continue
        raw_courses = fact.payload.get("courses")
        if not isinstance(raw_courses, list | tuple):
            continue
        for course in raw_courses:
            if not isinstance(course, dict):
                continue
            c_title = str(course.get("title") or "").strip()
            if not c_title or not _course_matches_relationship(c_title, referee.relationship):
                continue
            matched_edu_fact_ids.add(fact.id)
            grade = str(course.get("grade") or "").strip()
            credits = str(course.get("credits") or "").strip()
            detail = ", ".join(
                part
                for part in (
                    f"grade {grade}" if grade else "",
                    f"{credits} credits" if credits else "",
                )
                if part
            )
            line = f"Coursework: {c_title}" + (f" ({detail})" if detail else "")
            _add("coursework", line)

    # 6. Awards & distinctions linked to the referee or a matched thesis/project
    for fact in fact_list:
        if fact.category != VerifiedFact.Category.AWARD or not isinstance(fact.payload, dict):
            continue
        p = fact.payload
        award_name = str(p.get("name") or p.get("title") or "").strip()
        issuer = str(p.get("issuer") or p.get("organization") or p.get("institution") or "").strip()
        desc = str(p.get("description") or "").strip()
        blob = " ".join(part for part in (award_name, issuer, desc) if part)
        if not award_name:
            continue
        matches_award = (
            person_matches(referee.name, blob)
            or group_matches(referee.name, blob)
            or _relationship_mentions(referee.relationship, award_name)
            or any(_whole_word_match(t, blob) for t in qualifying_matched_titles)
        )
        if not matches_award:
            continue
        year = str(p.get("date") or p.get("year") or "").strip()
        parts = [f"Award: {award_name}", issuer, year]
        _add("award", ", ".join(part for part in parts if part), [desc] if desc else ())

    # 7. Institution-matched degree context when an academic referee shares the student's
    # university and no specific thesis or course on that degree was matched yet.
    if referee.institution and referee.kind == Referee.Kind.ACADEMIC:
        best_edu_line_by_inst: dict[str, tuple[int, str]] = {}
        for fact in fact_list:
            if (
                fact.category != VerifiedFact.Category.EDUCATION
                or not isinstance(fact.payload, dict)
                or fact.id in matched_edu_fact_ids
            ):
                continue
            p = fact.payload
            institution = str(p.get("institution_english") or p.get("institution_original") or "")
            degree = str(p.get("degree_english") or p.get("degree_as_awarded") or "")
            if (
                not institution
                or not degree
                or not institution_matches(referee.institution, institution)
            ):
                continue
            parts = [
                f"Degree at {institution}: {degree}",
                _date_span(p),
                f"grade {p['grade_native']}" if p.get("grade_native") else "",
            ]
            line = ", ".join(part for part in parts if part)
            inst_key = institution.strip().casefold()
            prev = best_edu_line_by_inst.get(inst_key)
            if prev is None or len(degree) > prev[0]:
                best_edu_line_by_inst[inst_key] = (len(degree), line)
        for _deg_len, line in best_edu_line_by_inst.values():
            _add("education", line)

    return tuple(items)


RefereeRoleArchetype = Literal[
    "research_supervisor", "course_instructor", "professional_supervisor"
]


@dataclass(frozen=True)
class ScopedRefereeEvidence:
    """Epistemically scoped and orthogonally partitioned evidence for a single referee."""

    role_archetype: RefereeRoleArchetype
    angle: str
    direct_work: tuple[SharedWorkItem, ...]
    scoped_facts: tuple[VerifiedFact, ...]
    scoped_courses: tuple[str, ...]
    co_referee_coverage: tuple[str, ...] = ()


def classify_referee_role(
    referee: Referee, shared_work: Sequence[SharedWorkItem]
) -> RefereeRoleArchetype:
    """Classify the referee into one of three primary-source narrative archetypes."""
    if referee.kind == Referee.Kind.PROFESSIONAL:
        return "professional_supervisor"
    kinds = {item.kind for item in shared_work}
    rel = referee.relationship.casefold().replace("i̇", "i")
    if kinds & {"research", "publication", "github", "pdf"} or any(
        marker in rel for marker in _RESEARCH_ROLE_MARKERS
    ):
        return "research_supervisor"
    if "coursework" in kinds or any(
        marker in rel for marker in _TEACHING_ROLE_MARKERS
    ):
        return "course_instructor"
    if any(marker in rel for marker in _PROFESSIONAL_ROLE_MARKERS):
        return "professional_supervisor"
    if "experience" in kinds:
        return "research_supervisor"
    if any(m in rel for m in ("advis", "mentor", "lab", "rəhbər", "rehber")):
        return "research_supervisor"
    return "course_instructor"


def _item_directly_anchored_to(
    item: SharedWorkItem,
    referee: Referee,
    facts: Sequence[VerifiedFact],
) -> bool:
    """True when `item` is anchored to `referee` by name, supervisor, author, or relationship note
    (as opposed to a fallback institution-only match)."""
    if item.kind in {"research", "publication", "coursework", "github", "pdf"}:
        return True
    if item.kind == "education":
        return False
    if _relationship_mentions(referee.relationship, item.summary):
        return True
    for fact in facts:
        if not isinstance(fact.payload, dict):
            continue
        p = fact.payload
        sup = str(p.get("supervisor") or "")
        grp = str(p.get("group") or "")
        proj = str(p.get("project") or "")
        title = str(p.get("title") or p.get("name") or "")
        if (sup and (person_matches(referee.name, sup) or group_matches(referee.name, sup))) or (
            grp and group_matches(referee.name, grp)
        ):
            if (proj and _whole_word_match(proj, item.summary)) or (
                title and _whole_word_match(title, item.summary)
            ):
                return True
    return False


def _research_matches_referee(p: dict[str, Any], referee: Referee) -> bool:
    supervisor = str(p.get("supervisor") or "")
    thesis = str(p.get("thesis_title") or p.get("project_title") or "")
    sup_match = bool(
        supervisor
        and (person_matches(referee.name, supervisor) or group_matches(referee.name, supervisor))
    )
    return sup_match or bool(thesis and _relationship_mentions(referee.relationship, thesis))


def _experience_matches_referee(
    p: dict[str, Any], referee: Referee, *, allow_institution: bool = True
) -> bool:
    supervisor = str(p.get("supervisor") or "")
    group = str(p.get("group") or "")
    project = str(p.get("project") or "")
    title = str(p.get("title") or "")
    employer = str(p.get("employer") or "")
    sup_match = bool(
        supervisor
        and (person_matches(referee.name, supervisor) or group_matches(referee.name, supervisor))
    )
    direct = bool(
        sup_match
        or (group and group_matches(referee.name, group))
        or (project and _relationship_mentions(referee.relationship, project))
        or (title and _relationship_mentions(referee.relationship, title))
    )
    if direct:
        return True
    if allow_institution and referee.institution and employer:
        return institution_matches(referee.institution, employer)
    return False


def _publication_matches_referee(p: dict[str, Any], referee: Referee) -> bool:
    raw_authors = p.get("authors")
    authors = (
        [str(a) for a in raw_authors if isinstance(a, str)]
        if isinstance(raw_authors, list | tuple)
        else []
    )
    pub_title = str(p.get("title") or "")
    return bool(
        any(person_matches(referee.name, author) for author in authors)
        or (pub_title and _relationship_mentions(referee.relationship, pub_title))
    )


def _award_matches_referee(p: dict[str, Any], referee: Referee) -> bool:
    award_name = str(p.get("name") or p.get("title") or "").strip()
    issuer = str(
        p.get("issuer")
        or p.get("awarding_body")
        or p.get("organization")
        or p.get("institution")
        or ""
    ).strip()
    desc = str(p.get("description") or "").strip()
    blob = " ".join(part for part in (award_name, issuer, desc) if part)
    if not award_name:
        return False
    return bool(
        person_matches(referee.name, blob)
        or group_matches(referee.name, blob)
        or _relationship_mentions(referee.relationship, award_name)
    )


def scope_evidence_for_referee(
    referee: Referee,
    *,
    facts: Iterable[VerifiedFact],
    readings: Sequence[UsableReading] = (),
    co_referees: Sequence[Referee] = (),
) -> ScopedRefereeEvidence:
    """Apply Rule 1 (Strict Per-Referee Epistemic Scoping) and Rule 2 (Orthogonal
    Multi-Referee Fact Partitioning) across `referee` and `co_referees`.

    1. Epistemic Scoping:
       - A referee never claims firsthand observation of research supervised by a
         different named person, or employment at an unrelated organization.
       - A professional/employer referee (`Referee.Kind.PROFESSIONAL`) receives only
         workplace experience, applied skills, and directly linked outcomes — never
         university transcript course lists or academic theses supervised by faculty.
    2. Orthogonal Multi-Referee Partitioning:
       - When co-referees share an application, any episode (`SharedWorkItem`),
         course, research project, or workplace role directly anchored to a co-referee
         is partitioned exclusively to that co-referee so two letters never repeat the
         same concrete body-paragraph episode.
    """
    fact_list = list(facts)
    other_refs = [co for co in co_referees if co.id != referee.id]
    raw_direct = shared_work_for_referee(referee, facts=fact_list, readings=readings)

    co_work_map: dict[Any, tuple[SharedWorkItem, ...]] = {
        co.id: shared_work_for_referee(co, facts=fact_list, readings=readings)
        for co in other_refs
    }
    co_roles: dict[Any, RefereeRoleArchetype] = {
        co.id: classify_referee_role(co, co_work_map[co.id]) for co in other_refs
    }

    # Partition SharedWorkItem episodes so co-referees never duplicate body episodes.
    co_directly_claimed_keys: set[str] = set()
    co_all_keys: set[str] = set()
    for co in other_refs:
        for item in co_work_map[co.id]:
            key = f"{item.kind}:{_norm(item.summary)}"
            co_all_keys.add(key)
            if _item_directly_anchored_to(item, co, fact_list):
                co_directly_claimed_keys.add(key)

    partitioned_work: list[SharedWorkItem] = []
    for item in raw_direct:
        key = f"{item.kind}:{_norm(item.summary)}"
        is_direct_mine = _item_directly_anchored_to(item, referee, fact_list)
        if key in co_directly_claimed_keys and not is_direct_mine:
            continue
        if key in co_all_keys and not is_direct_mine:
            # Deterministic tie-break for institution-only fallback items
            owner_ids = sorted(
                str(r.id)
                for r in [referee, *other_refs]
                if any(
                    f"{w.kind}:{_norm(w.summary)}" == key
                    for w in (raw_direct if r.id == referee.id else co_work_map[r.id])
                )
            )
            if owner_ids and owner_ids[0] != str(referee.id):
                continue
        partitioned_work.append(item)

    direct_work = tuple(partitioned_work)
    role_archetype = classify_referee_role(referee, direct_work or raw_direct)
    angle = referee_angle(referee, direct_work or raw_direct)

    has_research_co_ref = any(r == "research_supervisor" for r in co_roles.values())
    has_course_co_ref = any(r == "course_instructor" for r in co_roles.values())

    # Partition transcript courses across academic referees
    co_claimed_courses: set[str] = set()
    for co in other_refs:
        if co.kind != Referee.Kind.ACADEMIC:
            continue
        for fact in fact_list:
            if (
                fact.category != VerifiedFact.Category.EDUCATION
                or not isinstance(fact.payload, dict)
            ):
                continue
            raw_courses = fact.payload.get("courses")
            if not isinstance(raw_courses, list | tuple):
                continue
            for c in raw_courses:
                if isinstance(c, dict) and c.get("title"):
                    c_title = str(c["title"]).strip()
                    if _course_matches_relationship(c_title, co.relationship):
                        co_claimed_courses.add(c_title.casefold())

    scoped_courses: list[str] = []
    seen_courses: set[str] = set()
    if referee.kind == Referee.Kind.ACADEMIC:
        # First pass: courses explicitly mentioned in this referee's relationship
        for fact in fact_list:
            if (
                fact.category != VerifiedFact.Category.EDUCATION
                or not isinstance(fact.payload, dict)
            ):
                continue
            raw_courses = fact.payload.get("courses")
            if not isinstance(raw_courses, list | tuple):
                continue
            for c in raw_courses:
                if not isinstance(c, dict) or not c.get("title"):
                    continue
                c_title = str(c["title"]).strip()
                key_c = c_title.casefold()
                if key_c in seen_courses:
                    continue
                if _course_matches_relationship(c_title, referee.relationship):
                    seen_courses.add(key_c)
                    c_grade = str(c.get("grade") or "").strip()
                    scoped_courses.append(f"{c_title} ({c_grade})" if c_grade else c_title)
        # Second pass: if this referee is a course instructor (or no course co-referee claims them),
        # include unclaimed verified courses up to 5.
        if not (role_archetype == "research_supervisor" and has_course_co_ref):
            for fact in fact_list:
                if (
                    fact.category != VerifiedFact.Category.EDUCATION
                    or not isinstance(fact.payload, dict)
                ):
                    continue
                raw_courses = fact.payload.get("courses")
                if not isinstance(raw_courses, list | tuple):
                    continue
                for c in raw_courses:
                    if not isinstance(c, dict) or not c.get("title") or len(scoped_courses) >= 5:
                        continue
                    c_title = str(c["title"]).strip()
                    key_c = c_title.casefold()
                    if key_c in seen_courses or key_c in co_claimed_courses:
                        continue
                    seen_courses.add(key_c)
                    c_grade = str(c.get("grade") or "").strip()
                    scoped_courses.append(f"{c_title} ({c_grade})" if c_grade else c_title)

    # Pre-select the richest EDUCATION fact per institution so profile-bridge duplicates
    # ("BSc" vs "BSc Chemistry" at the same university) never repeat on the facts sheet.
    best_edu_fact_ids: set[Any] = set()
    best_edu_by_inst: dict[str, tuple[int, Any]] = {}
    for fact in fact_list:
        if fact.category != VerifiedFact.Category.EDUCATION or not isinstance(fact.payload, dict):
            continue
        p = fact.payload
        inst = str(p.get("institution_english") or p.get("institution_original") or "").strip()
        deg = str(p.get("degree_english") or p.get("degree_as_awarded") or "").strip()
        inst_key = inst.casefold() or str(fact.id)
        score = len(deg) + (10 if p.get("start_date") else 0) + (20 if p.get("courses") else 0)
        prev = best_edu_by_inst.get(inst_key)
        if prev is None or score > prev[0]:
            best_edu_by_inst[inst_key] = (score, fact.id)
    best_edu_fact_ids = {fid for _s, fid in best_edu_by_inst.values()}

    # Filter VerifiedFact rows strictly to this referee's epistemic horizon
    scoped_facts: list[VerifiedFact] = []
    for fact in fact_list:
        if not isinstance(fact.payload, dict):
            continue
        p = fact.payload
        cat = fact.category

        if cat == VerifiedFact.Category.EDUCATION:
            if fact.id not in best_edu_fact_ids:
                continue
            if referee.kind == Referee.Kind.PROFESSIONAL:
                # Professional referees only get degree facts if from the same institution
                inst = str(p.get("institution_english") or p.get("institution_original") or "")
                if referee.institution and inst and institution_matches(referee.institution, inst):
                    scoped_facts.append(fact)
            else:
                scoped_facts.append(fact)

        elif cat == VerifiedFact.Category.RESEARCH:
            if referee.kind == Referee.Kind.PROFESSIONAL and not _research_matches_referee(
                p, referee
            ):
                continue
            sup = str(p.get("supervisor") or "").strip()
            mine = _research_matches_referee(p, referee)
            claimed_by_co = any(_research_matches_referee(p, co) for co in other_refs)
            if mine:
                scoped_facts.append(fact)
            elif sup:
                # Named a different supervisor -> outside this referee's firsthand supervision
                continue
            elif claimed_by_co:
                continue
            elif role_archetype == "course_instructor" and has_research_co_ref:
                continue
            else:
                scoped_facts.append(fact)

        elif cat == VerifiedFact.Category.PUBLICATION:
            mine = _publication_matches_referee(p, referee)
            claimed_by_co = any(_publication_matches_referee(p, co) for co in other_refs)
            if mine or (
                role_archetype == "research_supervisor"
                and not claimed_by_co
                and referee.kind == Referee.Kind.ACADEMIC
            ):
                scoped_facts.append(fact)

        elif cat == VerifiedFact.Category.EXPERIENCE:
            mine_direct = _experience_matches_referee(p, referee, allow_institution=False)
            mine_inst = _experience_matches_referee(p, referee, allow_institution=True)
            claimed_by_co_direct = any(
                _experience_matches_referee(p, co, allow_institution=False) for co in other_refs
            )
            claimed_by_co_inst = any(
                _experience_matches_referee(p, co, allow_institution=True) for co in other_refs
            )
            if mine_direct:
                scoped_facts.append(fact)
            elif claimed_by_co_direct:
                continue
            elif mine_inst:
                if claimed_by_co_inst and referee.kind == Referee.Kind.ACADEMIC and any(
                    co.kind == Referee.Kind.PROFESSIONAL
                    and _experience_matches_referee(p, co, allow_institution=True)
                    for co in other_refs
                ):
                    continue
                scoped_facts.append(fact)

        elif cat == VerifiedFact.Category.AWARD:
            mine = _award_matches_referee(p, referee)
            claimed_by_co = any(_award_matches_referee(p, co) for co in other_refs)
            if mine:
                scoped_facts.append(fact)
            elif claimed_by_co:
                continue
            elif referee.kind == Referee.Kind.ACADEMIC:
                if role_archetype == "course_instructor" and has_research_co_ref:
                    continue
                scoped_facts.append(fact)

        elif cat in (VerifiedFact.Category.SKILL, VerifiedFact.Category.LANGUAGE):
            scoped_facts.append(fact)

    co_coverage: list[str] = []
    for co in other_refs:
        co_w = co_work_map[co.id]
        co_ang = referee_angle(co, co_w)
        kind_label = co.get_kind_display().lower()
        detail = f"{kind_label}, {co.institution}" if co.institution else kind_label
        co_coverage.append(f"{co.label} ({detail}) — {co_ang.lower()}")

    return ScopedRefereeEvidence(
        role_archetype=role_archetype,
        angle=angle,
        direct_work=direct_work,
        scoped_facts=tuple(scoped_facts),
        scoped_courses=tuple(scoped_courses),
        co_referee_coverage=tuple(co_coverage),
    )

