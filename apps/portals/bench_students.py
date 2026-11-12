"""Synthetic applicants for the bench (spec §9). Never copied from a real student.

Keys are fact keys only (`profile.LEARNABLE_FIELDS`, plus the packet's
`contact.email`), because those are the only keys a learned map ever asks for:
a sample value under any other key would never meet a box. The hard name cases
therefore live in `identity.full_name`. Together the samples hold a value for
every LEARNABLE_FIELDS key and a document of every slot kind, because an entry
or a box no sample can fill is untested and blocks the report (a test pins it)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Variant = Literal["ORIGINAL", "TRANSLATION"]


@dataclass(frozen=True)
class SampleStudent:
    name: str
    values: dict[str, str]
    documents: tuple[tuple[str, str, Variant], ...] = field(default_factory=tuple)


_ID_DOCUMENT = {
    "id_document.document_type": "passport",
    "id_document.number": "C01X00T47",
    "id_document.issuing_country": "Azerbaijan",
    "id_document.issue_date": "2021-05-20",
    "id_document.expiry_date": "2031-05-19",
    "id_document.issuing_authority": "MINISTRY OF INTERNAL AFFAIRS",
}


def _identity(full_name: str, phone: str) -> dict[str, str]:
    return {
        "identity.full_name": full_name,
        # The typed given name (file-name rules, plan 4): the first word. The surname is the
        # passport's, below, as a passport read writes it.
        "identity.given_name": full_name.split(" ", 1)[0],
        "identity.phone": phone,
        "identity.orcid": "0000-0002-1825-0097",  # ORCID's own fictitious example
        "identity.linkedin_url": "https://www.linkedin.com/in/elmify-bench-sample",
        "identity.linkedin_handle": "elmify-bench-sample",
        "identity.github_url": "https://github.com/elmify-bench-sample",
        "identity.github_username": "elmify-bench-sample",
        "identity.website_url": "https://bench.example.org",
        "identity.date_of_birth": "1998-03-14",
        "identity.sex": "F",
        "identity.citizenship": "Azerbaijan",
        "identity.given_names": "NƏRMIN",
        "identity.surname": "BENCH-ƏLIYEVA",
        "identity.place_of_birth": "BAKU",
    }


def _degree(
    prefix: str, original: str, english: str, awarded: str, degree_english: str,
    start: str, end: str,
) -> dict[str, str]:
    detail = {
        "institution_original": original,
        "institution_english": english,
        "degree_as_awarded": awarded,
        "degree_english": degree_english,
        "start_date": start,
        "end_date": end,
        "city": "Bakı",
        "country": "Azerbaijan",
        "grade_native": "91.5",
        "grade_scale": "100",
        "grade_conversion": "1.7",
        "ects_credits": "120",
        "thesis_title": "A synthetic thesis for the portal bench",
        "class_rank": "3 of 120",
        "supervisor": "Dr. Bench Supervisor",
        "funding": "Bench State Scholarship",
        "relevant_coursework": "Statistics; Econometrics",
        "medium_of_instruction": "English",
        "diploma_number": "AB 123456",
    }
    return {f"{prefix}.{key}": value for key, value in detail.items()}


_OTHER_FACTS: dict[str, str] = {
    "experience.employer": "Bench Consulting LLC",
    "experience.title": "Junior Analyst",
    "experience.city": "Bakı",
    "experience.country": "Azerbaijan",
    "experience.start_date": "2018-07-01",
    "experience.end_date": "2019-08-31",
    "experience.bullets": "Built synthetic reports for the bench",
    "experience.supervisor": "Bench Manager",
    "experience.project": "Bench Project",
    "experience.group": "Bench Analytics",
    "experience.unpaid": "No",
    "research.thesis_title": "A synthetic research project",
    "research.supervisor": "Prof. Bench Researcher",
    "research.institution": "Bench Research Institute",
    "research.city": "Bakı",
    "research.country": "Azerbaijan",
    "research.start_date": "2021-01-01",
    "research.end_date": "2021-12-31",
    "research.methods": "Panel regression",
    "research.outcomes": "One synthetic working paper",
    "research.funding": "Bench Research Grant",
    "publication.title": "Synthetic Evidence from the Portal Bench",
    "publication.year": "2023",
    "publication.doi": "10.5555/bench.0001",
    "publication.authors": "N. Bench-Əliyeva; B. Coauthor",
    "publication.self_author_index": "1",
    "publication.venue": "Journal of Bench Studies",
    "publication.status": "Published",
    "publication.volume": "12",
    "publication.issue": "3",
    "publication.pages": "45-67",
    "publication.is_presentation": "No",
    "publication.url": "https://bench.example.org/paper",
    "award.title": "Bench Excellence Award",
    "award.date": "2022-05-20",
    "award.awarding_body": "Bench Foundation",
    "award.detail": "Top synthetic graduate",
    "language.language": "English",
    "language.cefr_level": "C1",
    "language.test_name": "TOEFL iBT",
    "language.test_score": "105",
    "language.listening": "C1",
    "language.reading": "C2",
    "language.spoken_interaction": "C1",
    "language.spoken_production": "C1",
    "language.writing": "B2",
    "language.mother_tongue": "Azerbaijani",
    "language.test_variant": "iBT",
    "language.test_date": "2025-11-08",
    "language.certificate_number": "0000 1111 2222 3333",
    "language.score_listening": "27",
    "language.score_reading": "28",
    "language.score_writing": "24",
    "language.score_speaking": "26",
    "skill.name": "Python",
    "skill.category": "Programming",
    "skill.kind": "Technical",
    "skill.evidence": "Bench coursework",
    "personal.summary": "A synthetic applicant who exists only on the portal bench.",
    "reference.name": "Prof. Bench Referee",
    "reference.email": "referee.bench@example.org",
    "reference.position": "Professor",
    "reference.institution": "Bench State University",
    "reference.phone": "+994 12 000 00 00",
    "reference.do_not_contact": "No",
    "timeline.start_date": "2019-09-01",
    "timeline.end_date": "2020-08-31",
    "timeline.statement": "A synthetic gap year spent volunteering",
    "certification.title": "First Aid Certificate",
    "certification.issuer": "Red Crescent Society",
    "certification.date": "2022-03-01",
    "narrative.motivation_letter": "A synthetic motivation letter for the portal bench.",
    "narrative.why_programme": "A synthetic statement on why this programme fits.",
    "narrative.why_country": "A synthetic statement on why this study destination fits.",
    "narrative.academic_preparation": "A synthetic summary of prior academic preparation.",
    "narrative.research_plan": "A synthetic research and study plan.",
    "narrative.career_plan": "A synthetic post-graduation career plan.",
    "narrative.home_country_contribution": "A synthetic home-country contribution statement.",
    "narrative.leadership_example": "A synthetic leadership example.",
    "narrative.personal_background": "A synthetic personal background note.",
    "narrative.language_plan": "A synthetic language preparation plan.",
    "narrative.relationship_community": "A synthetic community involvement note.",
    "narrative.opening": "Dear Admissions Committee,",
    "narrative.closing": "Sincerely, Nərmin Bench-Əliyeva",
}

for _cat in ("experience", "reference", "timeline"):
    _cat_items = [
        (k.split(".", 1)[1], v)
        for k, v in list(_OTHER_FACTS.items())
        if k.startswith(f"{_cat}.")
    ]
    for _idx in range(1, 4):
        for _key, _val in _cat_items:
            _OTHER_FACTS[f"{_cat}.{_idx}.{_key}"] = _val


SAMPLE_STUDENTS: tuple[SampleStudent, ...] = (
    SampleStudent(
        "long multi-part name with ə/ğ/ı",
        {
            "identity.full_name": "Gülnarə Ləman Məmmədova-Ağayeva",
            "identity.phone": "+994 50 123 45 67",
            "contact.email": "gulnare.bench@example.org",
            "education.1.institution_original": "Azərbaycan Dövlət İqtisad Universiteti",
            "education.1.institution_english": "Azerbaijan State University of Economics",
            "education.1.degree_as_awarded": "Bakalavr",
            "education.1.start_date": "2019-09-15",
            "education.1.end_date": "2023-06-30",
            "education.1.country": "Azerbaijan",
            "education.1.city": "Bakı",
        },
        (
            ("transcript-az.pdf", "TRANSCRIPT", "ORIGINAL"),
            ("transcript-en.pdf", "TRANSCRIPT", "TRANSLATION"),
            ("passport.pdf", "PASSPORT", "ORIGINAL"),
        ),
    ),
    SampleStudent(
        "two degrees",
        {
            "identity.full_name": "Rauf Hüseynov",
            "identity.phone": "+994 55 765 43 21",
            "contact.email": "rauf.bench@example.org",
            "education.1.institution_original": "Bakı Dövlət Universiteti",
            "education.1.institution_english": "Baku State University",
            "education.1.degree_as_awarded": "Bakalavr",
            "education.1.start_date": "2016-09-15",
            "education.1.end_date": "2020-06-30",
            "education.1.country": "Azerbaijan",
            "education.1.city": "Bakı",
            "education.2.institution_original": "ADA University",
            "education.2.institution_english": "ADA University",
            "education.2.degree_as_awarded": "Magistr",
            "education.2.start_date": "2020-09-15",
            "education.2.end_date": "2022-06-30",
            "education.2.country": "Azerbaijan",
            "education.2.city": "Bakı",
        },
        (
            ("bsc.pdf", "TRANSCRIPT", "ORIGINAL"),
            ("msc.pdf", "TRANSCRIPT", "ORIGINAL"),
            ("bsc-diploma.pdf", "DIPLOMA", "ORIGINAL"),
            ("msc-diploma.pdf", "DIPLOMA", "ORIGINAL"),
            ("cv.pdf", "CV", "ORIGINAL"),
        ),
    ),
    SampleStudent(
        "Turkish dotted and dotless i",
        {
            "identity.full_name": "Işıl İpek Öztürk",
            "identity.phone": "+90 532 111 22 33",
            "contact.email": "isil.bench@example.org",
            "education.1.institution_original": "İstanbul Teknik Üniversitesi",
            "education.1.institution_english": "Istanbul Technical University",
            "education.1.degree_as_awarded": "Lisans",
            "education.1.start_date": "2018-09-01",
            "education.1.end_date": "2022-01-15",
            "education.1.country": "Türkiye",
            "education.1.city": "İstanbul",
        },
        (("cv.pdf", "CV", "ORIGINAL"), ("ielts.pdf", "LANGUAGE_CERTIFICATE", "ORIGINAL")),
    ),
    SampleStudent(
        "single name",
        {
            "identity.full_name": "Aynur",
            "contact.email": "aynur.bench@example.org",
            "education.1.institution_original": "Gəncə Dövlət Universiteti",
            "education.1.end_date": "2021-07-01",
        },
    ),
    SampleStudent(
        "every fact the ledger holds, three degrees",
        {
            **_identity("Nərmin Bench-Əliyeva", "+994 50 000 00 01"),
            **_ID_DOCUMENT,
            "contact.email": "nermin.bench@example.org",
            **_degree(
                "education.1", "Bench Dövlət Universiteti", "Bench State University",
                "Bakalavr", "Bachelor of Economics", "2014-09-15", "2018-06-30",
            ),
            **_degree(
                "education.2", "Bench Texniki Universiteti", "Bench Technical University",
                "Magistr", "Master of Science", "2018-09-15", "2020-06-30",
            ),
            **_degree(
                "education.3", "Bench Doktorantura Mərkəzi", "Bench Doctoral Centre",
                "Fəlsəfə doktoru", "Doctor of Philosophy", "2020-10-01", "2024-07-01",
            ),
            # The unindexed keys are the last degree, as verified_values gives them.
            **_degree(
                "education", "Bench Doktorantura Mərkəzi", "Bench Doctoral Centre",
                "Fəlsəfə doktoru", "Doctor of Philosophy", "2020-10-01", "2024-07-01",
            ),
            **_OTHER_FACTS,
        },
        (
            ("bench-cv.pdf", "CV", "ORIGINAL"),
            ("bench-transcript.pdf", "TRANSCRIPT", "ORIGINAL"),
            ("bench-diploma.pdf", "DIPLOMA", "ORIGINAL"),
            ("bench-passport.pdf", "PASSPORT", "ORIGINAL"),
            ("bench-toefl.pdf", "LANGUAGE_CERTIFICATE", "ORIGINAL"),
            ("bench-recommendation.pdf", "REFERENCE_LETTER", "ORIGINAL"),
            ("bench-motivation.pdf", "MOTIVATION_LETTER", "ORIGINAL"),
            ("bench-other.pdf", "OTHER", "ORIGINAL"),
        ),
    ),
)
