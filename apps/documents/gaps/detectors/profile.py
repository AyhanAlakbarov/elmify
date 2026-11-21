"""Profile and identity detectors: missing contacts, passport name parts, and abbreviated names."""

from __future__ import annotations

from apps.documents.cv_fixes import (
    ABBREVIATED_NAME,
    abbreviated_degree,
    abbreviated_institution,
    full_title_for,
    reverted_subjects,
    subject_of,
)
from apps.documents.gaps.models import GapQuestion, Kind, _current
from apps.documents.models import VerifiedFact
from apps.documents.verification import disowned_refs, has_full_name, unsuperseded_facts
from apps.tenancy.models import Membership

#: (payload key, alternative key that also counts as present, prompt).
#: The alternative exists because extract_link_urls recovers addresses from a
#: PDF's link annotations while the prompt refuses to build a URL from a bare
#: handle -- so a CV printing "Github: 0rkhann" yields a username and no URL,
#: and is not missing anything a student needs to retype.
_CONTACT_FIELDS: tuple[tuple[str, str | None, str], ...] = (
    ("phone", None, "What phone number should the CV print?"),
    ("linkedin_url", "linkedin_handle", "What is your LinkedIn profile address?"),
    ("github_url", "github_username", "What is your GitHub profile address?"),
    ("website_url", None, "Do you have a personal or academic website?"),
    ("orcid", None, "What is your ORCID iD? (Optional — for researchers)"),
)

_CONTACT_EVIDENCE: dict[str, str] = {
    "phone": "No phone number is listed in your CV header yet.",
    "linkedin_url": (
        "No LinkedIn address is listed in your CV header yet (leave blank if you do not use one)."
    ),
    "github_url": (
        "No GitHub address is listed in your CV header yet (leave blank if not applicable)."
    ),
    "website_url": (
        "No personal or academic website is listed in your CV header yet (leave blank if none)."
    ),
    "orcid": (
        "No ORCID iD is listed in your CV header (only needed if you have academic publications)."
    ),
}


def missing_contact(student: Membership) -> tuple[GapQuestion, ...]:
    """Contact details the header has no value for.

    Cheapest to detect and cheapest to answer, so this should never be the
    reason a CV is weak. Asks only for what is genuinely absent.
    """
    fact = has_full_name(unsuperseded_facts(student)).last()
    if fact is None:
        return ()
    payload = fact.payload if isinstance(fact.payload, dict) else {}
    name = str(payload.get("full_name") or "your CV")
    return tuple(
        GapQuestion(
            kind=Kind.MISSING_CONTACT,
            fact_id=fact.id,
            payload_key=key,
            prompt=prompt,
            evidence=_CONTACT_EVIDENCE.get(
                key, f"The contact header for {name} has no {key.replace('_', ' ')}."
            ),
        )
        for key, alternative, prompt in _CONTACT_FIELDS
        if not payload.get(key) and not (alternative and payload.get(alternative))
    )


_NAME_PART_PROMPTS = (
    ("surname", "{surname}", "Your surname exactly as in your passport (Latin letters)."),
    ("given_name", "{given_name}", "Your given name(s) exactly as in your passport."),
)
#: Keys a student types about themselves and which are stored confirmed.
#: PersonalInformation.surname / given_name max_length.
NAME_PART_MAX = 100
_NAME_PART_KEYS = frozenset(key for key, _, _ in _NAME_PART_PROMPTS)


def name_parts(student: Membership) -> tuple[GapQuestion, ...]:
    """Surname and given name, when an open application's file name needs them.

    One question per missing part. Not asked when no rule uses the placeholder,
    so a student whose programmes name files by full name never sees it.
    """
    # Lazy: apps.portals imports apps.documents, never the reverse at load time.
    from apps.portals.models import Application

    # The row that names the person: a passport writes one IDENTITY row per key.
    fact = has_full_name(unsuperseded_facts(student)).last()
    if fact is None or fact.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT:
        # Answering over it would raise and fail the whole submit; the file
        # keeps the name_needs_name_parts note instead.
        return ()
    held = {
        key
        # What prepare.jobs_for will read: confirmed, and never a disowned document's.
        for row in unsuperseded_facts(student)
        .filter(category=VerifiedFact.Category.IDENTITY)
        .exclude(source_ref__in=disowned_refs(student))
        if row == fact or row.confirmed_at is not None
        for key, value in (row.payload if isinstance(row.payload, dict) else {}).items()
        if value
    }
    if "given_names" in held:  # a passport's given names are the file name's given name
        held.add("given_name")
    patterns = [
        str(record.get("value"))
        for application in Application.objects.filter(student=student).exclude(
            state__in=(Application.State.SUBMITTED, Application.State.CONFIRMED)
        )
        for record in application.kit_file_rules or []
        if isinstance(record, dict) and record.get("field") == "name_pattern"
    ]
    return tuple(
        GapQuestion(
            kind=Kind.NAME_PARTS,
            fact_id=fact.id,
            payload_key=key,
            prompt=prompt,
            evidence="A programme you are applying to names the file with your "
            f"{key.replace('_', ' ')}.",
        )
        for key, placeholder, prompt in _NAME_PART_PROMPTS
        if key not in held and any(placeholder in pattern for pattern in patterns)
    )


def abbreviated_names(student: Membership) -> tuple[GapQuestion, ...]:
    """CV design §5.3: ask for a short degree title or institution in full.

    Not asked when a document the platform read already supplies the full
    degree title (generation takes it from there), nor for a value the student
    already retyped unchanged -- that is their diploma's own wording and is
    remembered as such (cv_fixes.ABBREVIATED_NAME).
    """
    facts = _current(student, VerifiedFact.Category.EDUCATION)
    as_printed = reverted_subjects(student, ABBREVIATED_NAME)
    questions: list[GapQuestion] = []
    for fact in facts:
        if fact.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT:
            continue
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        degree = str(payload.get("degree_as_awarded") or "")
        institution = str(payload.get("institution_original") or "")
        year = str(payload.get("end_date") or "")[:4]
        if (
            degree
            and abbreviated_degree(degree)
            and subject_of(ABBREVIATED_NAME, degree) not in as_printed
            and full_title_for(
                degree,
                institution,
                int(year) if year.isdigit() else None,
                facts,
            )
            is None
        ):
            questions.append(
                GapQuestion(
                    kind=Kind.ABBREVIATED_NAME,
                    fact_id=fact.id,
                    payload_key="degree_as_awarded",
                    prompt=(
                        "Write this degree in full, exactly as your diploma states it. "
                        "If your diploma writes it exactly like this, type it again unchanged."
                    ),
                    evidence=f"Your CV writes it as “{degree}”.",
                )
            )
        if (
            institution
            and abbreviated_institution(institution)
            and subject_of(ABBREVIATED_NAME, institution) not in as_printed
        ):
            questions.append(
                GapQuestion(
                    kind=Kind.ABBREVIATED_NAME,
                    fact_id=fact.id,
                    payload_key="institution_original",
                    prompt=(
                        "Write your university's name in full, exactly as your diploma states "
                        "it. If your diploma writes it exactly like this, type it again "
                        "unchanged."
                    ),
                    evidence=f"Your CV writes it as “{institution}”.",
                )
            )
    return tuple(questions)
