"""Is this degree one the student already holds? (transcript plan 3b Task 7)

A CV says "Baku State University, BSc Chemistry"; the transcript says "Bakı Dövlət
Universiteti, Bakalavr". Names alone cannot decide that (two languages, abbreviations), so
every signal is used -- the name folded every way we know, initials, names an earlier document
taught us (`aliases`), the level, the end date -- and the answer is "same" or "different" only
when they are sure. Everything else is "ask": the student says, in one tap.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Literal
from uuid import UUID

from anyascii import anyascii

from apps.accounts.forms import normalize_country_code
from apps.tenancy.models import Membership

from . import mrz
from .confirmation import FactNotFound
from .hygiene import normalize_text
from .models import VerifiedFact
from .verification import (
    disowned_refs,
    live_retired_refs,
    retired_hides,
    retired_refs,
    unsuperseded_facts,
)

Level = Literal["bachelor", "master", "doctorate", "other"]
Verdict = Literal["same", "different", "ask"]


def _words(text: str) -> list[str]:
    """Romanised, casefolded words, an abbreviation's dots dropped: "M.Sc." is "msc"."""
    folded = anyascii(text).casefold().replace(".", "")
    return re.sub(r"[^\w]+", " ", folded).split()


#: Checked in this order: "yüksek lisans" is a master's, though "lisans" alone is a
#: bachelor's. Romanised first, so бакалавр reads as "bakalavr".
_LEVELS: tuple[tuple[Level, frozenset[str]], ...] = (
    (
        "doctorate",
        frozenset(
            {
                "phd",
                "dphil",
                "doctor",
                "doctorate",
                "doctoral",
                "doktor",
                "doktoru",
                "doktora",
                "doktorantura",
                "kandidat",
                "aspirantura",
                "md",
                "dsc",
            }
        ),
    ),
    (
        "master",
        frozenset(
            {
                "master",
                "masters",
                "magistr",
                "magister",
                "magistratura",
                "magistrale",
                "msc",
                "ma",
                "mba",
                "meng",
                "mphil",
                "mres",
                "ms",
                "mtech",
                "me",
                "llm",
                "mpa",
                "mpp",
                "med",
                "mfa",
                "march",
                "mlitt",
                "mst",
                "diplom",
                "spesialist",
                "spetsialist",
                "specialist",
            }
        ),
    ),
    (
        "bachelor",
        frozenset(
            {
                "bachelor",
                "bachelors",
                "bakalavr",
                "bakalavriat",
                "lisans",
                "bsc",
                "ba",
                "bs",
                "beng",
                "bba",
                "licence",
                "licenciatura",
                "btech",
                "be",
                "llb",
                "bed",
                "bfa",
                "barch",
                "bcom",
                "laurea",
                "triennale",
                "gakushi",
                "haksa",
                "xueshi",
            }
        ),
    ),
)


def degree_level(text: str) -> Level:
    words = _words(text)
    if "yuksek lisans" in " ".join(words):
        return "master"
    for level, keys in _LEVELS:
        if keys & set(words):
            return level
    return "other"


#: Words every university's name may carry, romanised the way `_words` romanises a name.
#: "State" is not one of them: Ohio State University and Ohio University are two
#: universities (final review, finding 7).
_GENERIC = frozenset(
    word
    for name in (
        "university",
        "universiteti",
        "üniversitesi",
        "университет",
        "universität",
        "universitat",
        "université",
        "universite",
        "università",
        "universita",
        "universidad",
        "universidade",
        "universiteit",
        "uniwersytet",
        "universitet",
        "universitatea",
        "yliopisto",
        "of",
        "the",
        "and",
        "de",
        "di",
        "del",
        "della",
        "degli",
        "für",
        "fur",
        "fuer",
        "van",
        "von",
        "zu",
    )
    for word in _words(name)
)


def institution_key(name: str) -> str:
    return " ".join(word for word in _words(name) if word not in _GENERIC)


def same_name(a: object, b: object) -> bool:
    """Same text, or the same words once spelled one way: "Bakı Dövlət Universiteti" and
    "BAKI DÖVLƏT UNİVERSİTETİ" casefold differently (dotless ı, dotted İ) and are one name.
    mrz.fold_tokens drops every non-Latin letter, so a fold is compared only when no
    word vanished: two Cyrillic names, or "Бакинский University" and "Московский
    University", are not one institution. (fact_writer's diploma lookup uses it too.)"""
    if normalize_text(str(a)).casefold() == normalize_text(str(b)).casefold():
        return True
    words = [str(a).split(), str(b).split()]
    folds = [mrz.fold_tokens(str(a)), mrz.fold_tokens(str(b))]
    return all(len(f) == len(w) for f, w in zip(folds, words, strict=True)) and folds[0] == folds[1]


def _initials(a: str, b: str) -> bool:
    """"BSU" and "Baku State University"."""
    short, long = sorted((_words(a), _words(b)), key=len)
    if not (len(short) == 1 and len(long) > 1 and len(short[0]) > 1):
        return False
    stop = {
        "of", "the", "and", "de", "di", "del", "della",
        "degli", "fur", "fuer", "van", "von", "zu",
    }
    return short[0] in (
        "".join(w[0] for w in long if w not in stop),
        "".join(w[0] for w in long),
    )


def _named(fact: dict[str, Any], record: dict[str, Any]) -> Literal["name", "initials", ""]:
    """How the fact names the record's institution: by name (an alias the transcript taught
    us counts -- the institution's, never the degree's, which every university shares), by
    initials only, or not at all."""
    institution = str(record.get("institution") or "")
    if not institution.strip():
        return ""
    aliases = {" ".join(_words(str(alias))) for alias in fact.get("aliases") or ()}
    if " ".join(_words(institution)) in aliases:
        return "name"
    initials = False
    for name in (fact.get("institution_original"), fact.get("institution_english")):
        if not isinstance(name, str) or not name.strip():
            continue
        key = institution_key(name)
        if (key and key == institution_key(institution)) or same_name(name, institution):
            return "name"
        initials = initials or _initials(name, institution)
    return "initials" if initials else ""


def _months(text: object) -> int | None:
    match = re.match(r"(\d{4})(?:-(\d{1,2}))?", str(text or ""))
    if match is None:
        return None
    return int(match[1]) * 12 + int(match[2] or 6)


def same_degree(fact_payload: dict[str, Any], record: dict[str, Any]) -> Verdict:
    """An EDUCATION fact's payload against an academic record (accounts.schemas.AcademicRecord
    as a dict). Different: two known levels differ, or two known end dates are more than a
    year apart. Same: the names match and nothing known disagrees -- levels equal or unknown,
    end dates within six months or unknown. Otherwise the student is asked."""
    if not isinstance(fact_payload, dict):
        return "ask"  # a malformed row decides nothing
    countries = (
        normalize_country_code(fact_payload.get("country")),
        normalize_country_code(record.get("country_code")),
    )
    if all(countries) and countries[0] != countries[1]:
        return "different"
    fact_level = next((level for text in (fact_payload.get("degree_as_awarded"),
                                          fact_payload.get("degree_english"))
                       if (level := degree_level(str(text or ""))) != "other"), "other")
    record_level = degree_level(str(record.get("qualification") or ""))
    if "other" not in (fact_level, record_level) and fact_level != record_level:
        return "different"
    ends = (_months(fact_payload.get("end_date")),
            _months(record.get("completed_on") or record.get("expected_completion")))
    apart = abs(ends[0] - ends[1]) if ends[0] is not None and ends[1] is not None else None
    if apart is not None and apart > 12:
        return "different"
    named = _named(fact_payload, record)
    if named == "name" and (apart is None or apart <= 6):
        return "same"
    # Initials name many universities ("BSU": Baku, Belarusian, Boise...): only with the level
    # and the end date both known and agreeing (final review, finding 7).
    if named == "initials" and "other" not in (fact_level, record_level) \
            and apart is not None and apart <= 6:
        return "same"
    return "ask"


def match_record(
    student: Membership, record: dict[str, Any]
) -> tuple[Literal["same", "different", "ask", "none"], VerifiedFact | None]:
    """The student's live degree this record is: one sure match wins; else the first one to
    ask about; else none of them ("different"), or no degree held at all ("none")."""
    # Live degrees only (final review, finding 5): a document's unconfirmed whole row is an
    # open "Is this a new degree?" question, not a degree, and a disowned or retired one is gone.
    disowned = disowned_refs(student)
    retired, live = retired_refs(student), live_retired_refs(student)
    facts = [
        fact for fact in unsuperseded_facts(student)
        .filter(category=VerifiedFact.Category.EDUCATION).exclude(source_ref__in=disowned)
        if not (
            fact.source_ref.startswith(("document:", "profile-bridge:"))
            and fact.confirmed_at is None
        )
        and not retired_hides(fact, retired, live)
    ]
    verdicts = [(same_degree(fact.payload, record), fact) for fact in facts]
    for wanted in ("same", "ask"):
        found = next((fact for verdict, fact in verdicts if verdict == wanted), None)
        if found is not None:
            return wanted, found
    return ("different", None) if facts else ("none", None)


def held_duplicates(facts: Iterable[VerifiedFact]) -> set[UUID]:
    """The ids of CV claims held back as possibly a degree already held: never confirmed in a
    batch, never offered as "these are right" -- until the student says it is a different
    degree (final review, finding 6)."""
    return {fact.id for fact in facts if fact.category == VerifiedFact.Category.EDUCATION
            and fact.confirmed_at is None and isinstance(fact.payload, dict)
            and fact.payload.get("possible_duplicate_of")}


def different_degree(*, student: Membership, fact_id: UUID) -> VerifiedFact:
    """"Different degree -- add it": the held claim again, without the marker, still the
    student's to confirm with the rest of the CV."""
    claim = unsuperseded_facts(student).filter(id=fact_id).first()
    if claim is None or claim.id not in held_duplicates([claim]):
        raise FactNotFound("not a held CV degree of this student")
    payload = {k: v for k, v in claim.payload.items() if k != "possible_duplicate_of"}
    return VerifiedFact.objects.create(
        student=student, category=claim.category, payload=payload,
        source_tier=claim.source_tier, source_ref=claim.source_ref,
        supersedes=claim, created_by=student,
    )
