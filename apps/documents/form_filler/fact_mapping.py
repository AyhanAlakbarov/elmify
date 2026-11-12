"""Deterministic mapping of student fact ledger records onto template form slots."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from apps.documents.hygiene import normalize_text
from apps.documents.models import VerifiedFact

from .models import _GENERIC_PLACEHOLDERS, FormSlot, _ascii_label_key


def _split_date_parts(raw_date: str) -> tuple[str, str, str]:
    """Return `(dd, mm, yyyy)` from ISO (`YYYY-MM-DD`, `YYYY-MM`) or slash (`DD/MM/YYYY`) dates."""
    clean = raw_date.strip()
    if not clean:
        return "", "", ""
    m_iso = re.match(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$", clean)
    if m_iso:
        yyyy = m_iso.group(1)
        mm = m_iso.group(2).zfill(2)
        dd = m_iso.group(3).zfill(2) if m_iso.group(3) else ""
        return dd, mm, yyyy
    m_slash = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$", clean)
    if m_slash:
        return m_slash.group(1).zfill(2), m_slash.group(2).zfill(2), m_slash.group(3)
    m_year = re.match(r"^(\d{4})$", clean)
    if m_year:
        return "", "", m_year.group(1)
    return "", "", ""


def _resolve_dropdown_choice(candidate: str, options: Sequence[str]) -> str | None:
    """Match `candidate` against allowed `options` (including sex/gender synonyms)."""
    clean = candidate.strip()
    if not clean:
        return None
    if not options:
        return clean
    non_placeholder = [
        opt for opt in options if opt.strip().casefold() not in _GENERIC_PLACEHOLDERS
    ]
    pool = non_placeholder or list(options)
    low = clean.casefold()
    for opt in pool:
        if opt.casefold() == low:
            return opt
    # Sex / gender synonym expansion across languages
    female_synonyms = {
        "f",
        "female",
        "woman",
        "weiblich",
        "femme",
        "femenino",
        "kadın",
        "kadin",
        "qadın",
        "qadin",
    }
    male_synonyms = {
        "m",
        "male",
        "man",
        "männlich",
        "mannlich",
        "homme",
        "masculino",
        "erkek",
        "kişi",
        "kisi",
    }
    if low in female_synonyms:
        for opt in pool:
            if opt.strip().casefold() in female_synonyms:
                return opt
    if low in male_synonyms:
        for opt in pool:
            if opt.strip().casefold() in male_synonyms:
                return opt
    for opt in pool:
        if low in opt.casefold() or opt.casefold() in low:
            return opt
    return None


@dataclass
class _StudentSlotProfile:
    given_names: str = ""
    surname: str = ""
    full_name: str = ""
    first_comma_last: str = ""
    dob: str = ""
    dob_dd: str = ""
    dob_mm: str = ""
    dob_yyyy: str = ""
    place_of_birth: str = ""
    sex: str = ""
    citizenship: str = ""
    passport_number: str = ""
    passport_issue_date: str = ""
    passport_expiry_date: str = ""
    passport_issuing_country: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    country_of_residence: str = ""
    orcid: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    website_url: str = ""
    target_programme: str = ""
    target_institution: str = ""
    educations: list[dict[str, Any]] = field(default_factory=list)
    experiences: list[dict[str, Any]] = field(default_factory=list)
    researches: list[dict[str, Any]] = field(default_factory=list)
    languages: list[dict[str, Any]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    awards: list[dict[str, Any]] = field(default_factory=list)
    publications: list[dict[str, Any]] = field(default_factory=list)
    courses_by_title: dict[str, dict[str, str]] = field(default_factory=dict)
    edu_inst: str = ""
    edu_deg: str = ""
    edu_field: str = ""
    edu_grade: str = ""
    edu_credits: str = ""
    edu_start: str = ""
    edu_end: str = ""
    edu_medium: str = ""
    edu_diploma_no: str = ""
    thesis_title: str = ""
    supervisor: str = ""
    lang_by_name: dict[str, dict[str, Any]] = field(default_factory=dict)
    mother_tongue_name: str = ""
    lang0: dict[str, Any] = field(default_factory=dict)
    cefr_level: str = ""
    test_score: str = ""
    test_name: str = ""
    test_date: str = ""
    cert_number: str = ""


def _build_slot_profile(
    facts: Iterable[VerifiedFact],
    *,
    student_name: str,
    student_email: str,
    target_programme: str,
    target_institution: str,
    passport_details: Mapping[str, str] | None,
) -> _StudentSlotProfile:
    passport = dict(passport_details or {})
    prof = _StudentSlotProfile(
        given_names=str(passport.get("given_names") or passport.get("given_name") or "").strip(),
        surname=str(passport.get("surname") or "").strip(),
        dob=str(passport.get("date_of_birth") or "").strip(),
        place_of_birth=str(passport.get("place_of_birth") or "").strip(),
        sex=str(passport.get("sex") or "").strip(),
        citizenship=str(passport.get("citizenship") or passport.get("nationality") or "").strip(),
        passport_number=str(passport.get("number") or "").strip(),
        passport_issue_date=str(passport.get("issue_date") or "").strip(),
        passport_expiry_date=str(passport.get("expiry_date") or "").strip(),
        passport_issuing_country=str(passport.get("issuing_country") or "").strip(),
        email=student_email.strip(),
        phone=str(passport.get("phone") or "").strip(),
        location=str(passport.get("location") or "").strip(),
        country_of_residence=str(passport.get("country_of_residence") or "").strip(),
        target_programme=target_programme,
        target_institution=target_institution,
    )

    fallback_name = student_name
    for fact in facts:
        p = fact.payload if isinstance(fact.payload, dict) else {}
        cat = str(fact.category).upper()
        if cat == "IDENTITY":
            prof.given_names = prof.given_names or str(
                p.get("given_names") or p.get("given_name") or ""
            ).strip()
            prof.surname = prof.surname or str(p.get("surname") or "").strip()
            if not (prof.given_names and prof.surname) and p.get("full_name"):
                fallback_name = fallback_name or str(p["full_name"]).strip()
            prof.dob = prof.dob or str(p.get("date_of_birth") or "").strip()
            prof.place_of_birth = prof.place_of_birth or str(p.get("place_of_birth") or "").strip()
            prof.sex = prof.sex or str(p.get("sex") or "").strip()
            prof.citizenship = prof.citizenship or str(
                p.get("citizenship") or p.get("nationality") or ""
            ).strip()
            prof.email = prof.email or str(p.get("email") or "").strip()
            prof.phone = prof.phone or str(p.get("phone") or "").strip()
            prof.location = prof.location or str(p.get("location") or "").strip()
            prof.orcid = prof.orcid or str(p.get("orcid") or "").strip()
            prof.linkedin_url = prof.linkedin_url or str(p.get("linkedin_url") or "").strip()
            prof.github_url = prof.github_url or str(p.get("github_url") or "").strip()
            prof.website_url = prof.website_url or str(p.get("website_url") or "").strip()
        elif cat == "ID_DOCUMENT":
            prof.passport_number = prof.passport_number or str(p.get("number") or "").strip()
            prof.passport_issue_date = (
                prof.passport_issue_date or str(p.get("issue_date") or "").strip()
            )
            prof.passport_expiry_date = (
                prof.passport_expiry_date or str(p.get("expiry_date") or "").strip()
            )
            prof.passport_issuing_country = (
                prof.passport_issuing_country or str(p.get("issuing_country") or "").strip()
            )
        elif cat == "PERSONAL":
            if not (prof.given_names and prof.surname) and p.get("full_name"):
                fallback_name = fallback_name or str(p["full_name"]).strip()
            prof.email = prof.email or str(p.get("email") or "").strip()
            prof.phone = prof.phone or str(p.get("phone") or "").strip()
            prof.location = prof.location or str(p.get("location") or "").strip()
            prof.citizenship = prof.citizenship or str(p.get("nationality") or "").strip()
        elif cat == "EDUCATION":
            prof.educations.append(p)
            raw_courses = p.get("courses")
            if isinstance(raw_courses, list | tuple):
                for c in raw_courses:
                    if isinstance(c, dict) and c.get("title"):
                        c_key = _ascii_label_key(str(c["title"]))
                        if c_key:
                            prof.courses_by_title[c_key] = {
                                "credits": str(c.get("credits") or c.get("ects") or "").strip(),
                                "grade": str(c.get("grade") or "").strip(),
                            }
        elif cat == "EXPERIENCE":
            prof.experiences.append(p)
        elif cat == "RESEARCH":
            prof.researches.append(p)
        elif cat in ("LANGUAGE", "TEST_SCORE"):
            prof.languages.append(p)
        elif cat == "REFERENCE":
            if not p.get("do_not_contact"):
                prof.references.append(p)
        elif cat == "AWARD":
            prof.awards.append(p)
        elif cat == "PUBLICATION":
            prof.publications.append(p)

    prof.full_name = f"{prof.given_names} {prof.surname}".strip() or fallback_name.strip()
    if prof.full_name and not (prof.given_names and prof.surname):
        parts = prof.full_name.split()
        if len(parts) >= 2:
            prof.given_names = prof.given_names or " ".join(parts[:-1])
            prof.surname = prof.surname or parts[-1]
        elif len(parts) == 1:
            prof.given_names = prof.given_names or parts[0]
    prof.first_comma_last = (
        f"{prof.given_names}, {prof.surname}"
        if (prof.given_names and prof.surname)
        else prof.full_name
    )
    prof.dob_dd, prof.dob_mm, prof.dob_yyyy = _split_date_parts(prof.dob)

    edu0 = prof.educations[0] if prof.educations else {}
    prof.edu_inst = str(
        edu0.get("institution_english") or edu0.get("institution_original") or ""
    ).strip()
    prof.edu_deg = str(edu0.get("degree_english") or edu0.get("degree_as_awarded") or "").strip()
    prof.edu_field = str(edu0.get("field") or "").strip()
    prof.edu_grade = str(edu0.get("grade_native") or edu0.get("gpa") or "").strip()
    prof.edu_credits = str(
        edu0.get("ects_credits") or edu0.get("total_credits") or edu0.get("ects") or ""
    ).strip()
    prof.edu_start = str(edu0.get("start_date") or "").strip()
    prof.edu_end = str(edu0.get("end_date") or "").strip()
    prof.edu_medium = str(edu0.get("medium_of_instruction") or "").strip()
    prof.edu_diploma_no = str(edu0.get("diploma_number") or "").strip()
    res0 = prof.researches[0] if prof.researches else {}
    prof.thesis_title = str(
        edu0.get("thesis_title") or res0.get("thesis_title") or res0.get("project_title") or ""
    ).strip()
    prof.supervisor = str(edu0.get("supervisor") or res0.get("supervisor") or "").strip()

    prof.lang_by_name = {
        str(entry.get("language") or "").strip().casefold(): entry
        for entry in prof.languages
        if entry.get("language")
    }
    prof.mother_tongue_name = next(
        (
            str(entry.get("language") or "").strip()
            for entry in prof.languages
            if entry.get("mother_tongue") and entry.get("language")
        ),
        "",
    )
    prof.lang0 = next(
        (
            entry
            for entry in prof.languages
            if entry.get("test_score") or entry.get("overall_score") or entry.get("test_name")
        ),
        next(
            (entry for entry in prof.languages if not entry.get("mother_tongue")),
            prof.languages[0] if prof.languages else {},
        ),
    )
    prof.cefr_level = str(prof.lang0.get("cefr_level") or "").strip()
    prof.test_score = str(
        prof.lang0.get("test_score") or prof.lang0.get("overall_score") or ""
    ).strip()
    prof.test_name = str(prof.lang0.get("test_name") or "").strip()
    prof.test_date = str(prof.lang0.get("test_date") or "").strip()
    prof.cert_number = str(prof.lang0.get("certificate_number") or "").strip()
    return prof


_SEX_HEADS = frozenset({"sex", "gender", "geschlecht", "sexe", "sexo", "cinsiyet"})
_FULL_NAME_HEADS = frozenset({
    "full name",
    "applicant full name",
    "full name of applicant",
    "applicant name",
    "name of applicant",
    "student name",
    "first name last name",
    "vor und nachname",
    "nom et prenom",
    "nombre completo",
    "ad soyad",
})
_GIVEN_NAME_HEADS = frozenset({
    "given name",
    "given names",
    "first name",
    "forename",
    "vorname",
    "prenom",
    "prenom de l etudiant",
    "nombre",
})
_SURNAME_HEADS = frozenset({
    "surname",
    "family name",
    "last name",
    "applicant surname",
    "nachname",
    "familienname",
    "nom de famille",
    "apellido",
    "soyad",
})

_SCALAR_HEAD_GETTERS: tuple[tuple[frozenset[str], Callable[[_StudentSlotProfile], str]], ...] = (
    (
        frozenset({
            "citizenship",
            "nationality",
            "country of citizenship",
            "staatsangehorigkeit",
            "nationalite",
            "nacionalidad",
        }),
        lambda p: p.citizenship,
    ),
    (
        frozenset({"place of birth", "city of birth", "geburtsort", "lieu de naissance"}),
        lambda p: p.place_of_birth,
    ),
    (
        frozenset({
            "passport number",
            "document number",
            "id number",
            "passnummer",
            "reisepassnummer",
        }),
        lambda p: p.passport_number,
    ),
    (
        frozenset({"passport issue date", "date of issue", "ausstellungsdatum"}),
        lambda p: p.passport_issue_date,
    ),
    (
        frozenset({
            "passport expiry date",
            "expiry date",
            "expiration date",
            "date of expiry",
            "ablaufdatum",
            "gultig bis",
        }),
        lambda p: p.passport_expiry_date,
    ),
    (
        frozenset({"issuing country", "country of issue", "ausstellungsland"}),
        lambda p: p.passport_issuing_country,
    ),
    (frozenset({"orcid", "orcid id"}), lambda p: p.orcid),
    (frozenset({"linkedin", "linkedin url"}), lambda p: p.linkedin_url),
    (frozenset({"github", "github url"}), lambda p: p.github_url),
    (frozenset({"website", "personal website", "portfolio url"}), lambda p: p.website_url),
    (
        frozenset({
            "target institution",
            "target university",
            "host university",
            "host institution",
        }),
        lambda p: p.target_institution,
    ),
    (
        frozenset({"mother tongue", "native language", "first language", "muttersprache"}),
        lambda p: p.mother_tongue_name,
    ),
    (
        frozenset({
            "overall score",
            "test score",
            "language score",
            "ielts score",
            "toefl score",
        }),
        lambda p: p.test_score,
    ),
    (frozenset({"language test", "test name", "english test"}), lambda p: p.test_name),
    (frozenset({"test date", "exam date", "date of test"}), lambda p: p.test_date),
    (frozenset({"trf number", "test report form number"}), lambda p: p.cert_number),
)


def _match_identity_or_contact(
    slot: FormSlot,
    head: str,
    tail: str,
    full_key: str,
    id_key: str,
    tokens: set[str],
    prof: _StudentSlotProfile,
) -> tuple[bool, str]:
    if head in prof.courses_by_title:
        c_info = prof.courses_by_title[head]
        if "ects" in tail or "credit" in tail:
            return True, c_info["credits"]
        if "grade" in tail or "note" in tail or "mark" in tail:
            return True, c_info["grade"]
        return True, c_info["credits"] or c_info["grade"]
    if (
        head in _SEX_HEADS
        or tail in _SEX_HEADS
        or (
            slot.kind in ("docx_dropdown", "pdf_dropdown")
            and {"female", "male"} <= {o.strip().casefold() for o in slot.options}
        )
    ):
        return True, prof.sex
    if any(k in head for k in ("date of birth", "birth date", "dob", "geburtsdatum")) or (
        "birth" in tokens and "date" in tokens
    ):
        if tail in ("dd", "day", "tag", "jour"):
            return True, prof.dob_dd
        if tail in ("mm", "month", "monat", "mois"):
            return True, prof.dob_mm
        if tail in ("yyyy", "year", "jahr", "annee"):
            return True, prof.dob_yyyy
        return True, prof.dob
    if head in ("first name last name", "name surname") and "," in slot.label:
        return True, prof.first_comma_last
    if (
        head in _FULL_NAME_HEADS
        or id_key in ("fullname", "applicantname", "studentname")
        or ("first name" in full_key and ("surname" in full_key or "last name" in full_key))
    ):
        return True, prof.full_name
    if head in _GIVEN_NAME_HEADS or id_key in (
        "givenname",
        "givennames",
        "firstname",
        "applicantgivenname",
    ):
        return True, prof.given_names
    if head in _SURNAME_HEADS or id_key in (
        "surname",
        "lastname",
        "familyname",
        "applicantsurname",
    ):
        return True, prof.surname
    if (
        head in ("email", "e mail", "email address", "e mail address", "e mail adresse")
        or "e mail address" in full_key
        or "email address" in full_key
    ):
        return True, prof.email
    if (
        head in ("phone", "telephone", "mobile", "phone number", "telefon", "telefonnummer")
        or "telephone number" in full_key
        or "phone number" in full_key
    ):
        return True, prof.phone
    if head == "country of residence":
        return True, prof.country_of_residence or prof.location
    if (
        head
        in (
            "address",
            "residential address",
            "current address",
            "city",
            "location",
            "anschrift",
        )
        or "residence address" in full_key
        or "residential address" in full_key
    ):
        return True, prof.location or prof.country_of_residence
    if head in (
        "target programme",
        "programme",
        "program",
        "degree track",
        "course of study",
        "studiengang",
        "masterprogramm",
        "prufungsfach",
    ) or id_key in ("targetprogramme", "degreetrack", "subjectfield"):
        return True, prof.target_programme
    for heads, getter in _SCALAR_HEAD_GETTERS:
        if head in heads:
            return True, getter(prof)
    return False, ""


_EDU_HEAD_SPECS: tuple[
    tuple[
        str,
        frozenset[str],
        Callable[[dict[str, Any], _StudentSlotProfile, int], str],
        Callable[[_StudentSlotProfile], str],
    ],
    ...,
] = (
    (
        "edu_inst",
        frozenset({
            "institution",
            "university",
            "name of institution",
            "name of university",
            "awarding institution",
            "hochschule",
            "universitat",
        }),
        lambda ep, _p, _n: str(
            ep.get("institution_english") or ep.get("institution_original") or ""
        ).strip(),
        lambda p: p.edu_inst,
    ),
    (
        "edu_deg",
        frozenset({
            "degree",
            "qualification",
            "degree title",
            "name of qualification",
            "abschluss",
            "diplome",
        }),
        lambda ep, _p, _n: str(
            ep.get("degree_english") or ep.get("degree_as_awarded") or ""
        ).strip(),
        lambda p: p.edu_deg,
    ),
    (
        "edu_field",
        frozenset({"field of study", "major", "subject", "studienfach"}),
        lambda ep, _p, _n: str(ep.get("field") or "").strip(),
        lambda p: p.edu_field,
    ),
    (
        "edu_grade",
        frozenset({
            "gpa",
            "cgpa",
            "grade",
            "overall grade",
            "average grade",
            "gesamtnote",
            "moyenne",
        }),
        lambda ep, _p, _n: str(ep.get("grade_native") or ep.get("gpa") or "").strip(),
        lambda p: p.edu_grade,
    ),
    (
        "edu_credits",
        frozenset({
            "ects",
            "ects credits",
            "ects credits completed",
            "total credits",
            "credits completed",
            "credit points",
            "leistungspunkte",
        }),
        lambda ep, _p, _n: str(
            ep.get("ects_credits") or ep.get("total_credits") or ep.get("ects") or ""
        ).strip(),
        lambda p: p.edu_credits,
    ),
    (
        "edu_start",
        frozenset({"start date", "enrolment date", "studienbeginn"}),
        lambda ep, _p, _n: str(ep.get("start_date") or "").strip(),
        lambda p: p.edu_start,
    ),
    (
        "edu_end",
        frozenset({"graduation date", "completion date", "date of award", "abschlussdatum"}),
        lambda ep, _p, _n: str(ep.get("end_date") or "").strip(),
        lambda p: p.edu_end,
    ),
    (
        "edu_medium",
        frozenset({"medium of instruction", "language of instruction", "unterrichtssprache"}),
        lambda ep, _p, _n: str(ep.get("medium_of_instruction") or "").strip(),
        lambda p: p.edu_medium,
    ),
    (
        "edu_diploma",
        frozenset({"diploma number", "certificate number", "urkundennummer"}),
        lambda ep, p, _n: str(ep.get("diploma_number") or "").strip() or p.cert_number,
        lambda p: p.edu_diploma_no or p.cert_number,
    ),
    (
        "edu_thesis",
        frozenset({
            "thesis",
            "thesis title",
            "dissertation title",
            "masterarbeit",
            "bachelorarbeit",
        }),
        lambda ep, p, next_idx: (
            str(ep.get("thesis_title") or "").strip()
            or (p.thesis_title if next_idx == 1 else "")
        ),
        lambda p: p.thesis_title,
    ),
    (
        "edu_sup",
        frozenset({"supervisor", "thesis supervisor", "advisor", "betreuer"}),
        lambda ep, p, next_idx: (
            str(ep.get("supervisor") or "").strip()
            or (p.supervisor if next_idx == 1 else "")
        ),
        lambda p: p.supervisor,
    ),
)


def _match_repeating_or_language(
    head: str,
    full_key: str,
    prof: _StudentSlotProfile,
    cursors: Counter[str],
) -> str:
    for cursor_key, heads, row_fn, zero_fn in _EDU_HEAD_SPECS:
        if head in heads:
            idx = cursors[cursor_key]
            if idx < len(prof.educations):
                ep = prof.educations[idx]
                cursors[cursor_key] = idx + 1
                return row_fn(ep, prof, idx + 1)
            return zero_fn(prof) if idx == 0 else ""

    if (
        head in (
            "organisation name",
            "organization name",
            "employer",
            "company",
            "name of employer",
            "name of organisation",
            "arbeitgeber",
        )
        or "employer s name" in full_key
        or "name of employer" in full_key
    ):
        idx = cursors["exp_org"]
        if idx < len(prof.experiences):
            cursors["exp_org"] = idx + 1
            return str(prof.experiences[idx].get("employer") or "").strip()
        return ""
    if (
        head in (
            "position",
            "position held",
            "job title",
            "title of position",
            "role",
            "occupation",
            "berufsbezeichnung",
        )
        or "occupation or position" in full_key
        or "position held" in full_key
    ):
        idx = cursors["exp_role"]
        if idx < len(prof.experiences):
            cursors["exp_role"] = idx + 1
            return str(prof.experiences[idx].get("title") or "").strip()
        return ""
    if (
        head in (
            "duties",
            "responsibilities",
            "key responsibilities",
            "description of duties",
            "aufgaben",
        )
        or "main tasks and responsibilities" in full_key
        or "description of duties" in full_key
    ):
        idx = cursors["exp_duty"]
        if idx < len(prof.experiences):
            raw_b = prof.experiences[idx].get("bullets")
            cursors["exp_duty"] = idx + 1
            if isinstance(raw_b, list | tuple):
                return " ".join(str(b).strip() for b in raw_b if str(b).strip())
        return ""

    if head in ("german level", "deutschkenntnisse", "german proficiency"):
        de_entry = prof.lang_by_name.get("german") or prof.lang_by_name.get("deutsch") or {}
        return str(de_entry.get("cefr_level") or de_entry.get("test_score") or "").strip()
    if head in ("french level", "french proficiency", "niveau de francais"):
        fr_entry = prof.lang_by_name.get("french") or prof.lang_by_name.get("francais") or {}
        return str(fr_entry.get("cefr_level") or fr_entry.get("test_score") or "").strip()
    if head in ("cefr", "cefr level", "english level", "language level", "sprachniveau"):
        en_entry = prof.lang_by_name.get("english") if "english" in head else None
        return str((en_entry or prof.lang0).get("cefr_level") or prof.cefr_level).strip()

    if head in (
        "referee",
        "referee name",
        "name of referee",
        "referee 1",
        "referee 2",
        "first referee",
        "second referee",
        "gutachter",
    ):
        idx = cursors["ref_name"]
        if idx < len(prof.references):
            rp = prof.references[idx]
            cursors["ref_name"] = idx + 1
            r_title = str(rp.get("position") or "").strip()
            r_name = str(rp.get("name") or "").strip()
            return (
                f"{r_title} {r_name}".strip()
                if r_title and not r_name.startswith(r_title)
                else r_name
            )
        return ""
    if head in ("referee email", "email of referee", "referee email address"):
        idx = cursors["ref_email"]
        if idx < len(prof.references):
            cursors["ref_email"] = idx + 1
            return str(prof.references[idx].get("email") or "").strip()
        return ""
    if head in ("referee institution", "referee university", "referee organisation"):
        idx = cursors["ref_inst"]
        if idx < len(prof.references):
            cursors["ref_inst"] = idx + 1
            return str(prof.references[idx].get("institution") or "").strip()
        return ""
    if head in ("awards", "honours and awards", "scholarships and prizes", "auszeichnungen"):
        return "; ".join(
            str(a.get("title") or a.get("name") or "").strip()
            for a in prof.awards
            if str(a.get("title") or a.get("name") or "").strip()
        )
    if head in ("publications", "list of publications", "publikationen"):
        return "; ".join(
            str(pub.get("title") or "").strip()
            for pub in prof.publications
            if str(pub.get("title") or "").strip()
        )
    return ""


def map_student_facts_to_slots(
    slots: Sequence[FormSlot],
    *,
    facts: Iterable[VerifiedFact],
    student_name: str = "",
    student_email: str = "",
    target_programme: str = "",
    target_institution: str = "",
    passport_details: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Deterministically map a student's confirmed `VerifiedFact` records, passport
    reading, and target application metadata onto `slots` (keyed by `slot.slot_id`)."""
    prof = _build_slot_profile(
        facts,
        student_name=student_name,
        student_email=student_email,
        target_programme=target_programme,
        target_institution=target_institution,
        passport_details=passport_details,
    )
    mapped: dict[str, str] = {}
    cursors: Counter[str] = Counter()

    for slot in slots:
        if slot.kind in ("docx_checkbox", "pdf_checkbox"):
            continue
        raw_head, _, raw_tail = slot.label.partition("—")
        head = _ascii_label_key(raw_head)
        tail = _ascii_label_key(raw_tail)
        full_key = _ascii_label_key(slot.label)
        id_key = _ascii_label_key(slot.slot_id.partition(":")[2] or slot.slot_id)
        tokens = set(full_key.split()) | set(id_key.split())

        matched, candidate = _match_identity_or_contact(
            slot, head, tail, full_key, id_key, tokens, prof
        )
        if not matched:
            candidate = _match_repeating_or_language(head, full_key, prof, cursors)
        if not candidate:
            continue
        if slot.kind in ("docx_dropdown", "pdf_dropdown") and slot.options:
            resolved_opt = _resolve_dropdown_choice(candidate, slot.options)
            if resolved_opt is None:
                continue
            candidate = resolved_opt
        mapped[slot.slot_id] = normalize_text(candidate)

    return mapped


