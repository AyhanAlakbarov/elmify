import io

import pytest
from pypdf import PdfReader

from apps.documents.entry_selection import select_best_entries
from apps.documents.funder_templates.rhodes import render_rhodes
from apps.documents.funder_templates.sisgp import render_sisgp
from apps.documents.render import render_cv_with_warnings
from apps.documents.schemas import (
    AwardEntry,
    CVContent,
    EducationEntry,
    ExperienceEntry,
    PersonalInformation,
    PublicationEntry,
)

# R-066: Rhodes' six numbered, fixed-order sections -- no Education.
_RHODES_HEADINGS = (
    "1. PROFESSIONAL/RESEARCH/INTERNSHIP",
    "2. VOLUNTEERING/COMMUNITY/LEADERSHIP",
    "3. PUBLICATIONS AND PRESENTATIONS",
    "4. AWARDS/PRIZES/SCHOLARSHIPS",
    "5. SKILLS/HOBBIES/EXTRACURRICULAR",
    "6. OTHER",
)

# R-064: SISGP's five fixed-order sections.
_SISGP_HEADINGS = (
    "PERSONAL INFORMATION",
    "WORK EXPERIENCE",
    "EDUCATION AND TRAINING",
    "NETWORK/CIVIL SOCIETY ENGAGEMENT",
    "PREVIOUS SCHOLARSHIPS/AWARDS",
)


def _experience(count):
    return tuple(
        ExperienceEntry(
            employer=f"Employer {index}",
            title="Role",
            city="Berlin",
            country="DE",
            start_date=f"20{20 + index:02d}-01-01",
            bullets=(f"desc {index}",),
        )
        for index in range(count)
    )


def _content(experience_count=5, **overrides):
    fields = {
        "personal_information": PersonalInformation(
            full_name="Jane Doe",
            email="jane@example.com",
            sex="F",
            citizenship="AZ",
            date_of_birth="1999-05-04",
        ),
        "education": (
            EducationEntry(
                degree_as_awarded="BSc",
                institution_original="Example University",
                city="Berlin",
                country="DE",
                start_date="2020-09-01",
            ),
        ),
        "experience": _experience(experience_count),
        "research": (),
        "publications": (),
        "awards": (),
        "skills": (),
        "languages": (),
        "document_language": "en",
    }
    fields.update(overrides)
    return CVContent(**fields)


def _text(artifact):
    return "".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(artifact.pdf_bytes)).pages
    )


def _assert_headings_in_order(text, headings):
    """Every heading is present, and each appears strictly after the last --
    i.e. the rendered section order matches the funder's mandated order."""
    last_index = -1
    for heading in headings:
        index = text.find(heading)
        assert index != -1, f"heading {heading!r} missing from rendered text"
        assert index > last_index, f"heading {heading!r} is out of order"
        last_index = index


def test_select_best_entries_truncates_and_preserves_order_on_ties():
    assert select_best_entries(("a", "b", "c", "d"), limit=2) == ("a", "b")


def test_select_best_entries_ranks_by_key_then_original_order():
    # The two n=3 entries are tagged so a flipped tie-order would be caught --
    # plain {"n": 3} == {"n": 3} regardless of which physical dict lands
    # where, so an untagged pair can never fail this assertion.
    entries = (
        {"n": 1, "tag": "d"},
        {"n": 3, "tag": "a"},
        {"n": 3, "tag": "b"},
        {"n": 2, "tag": "c"},
    )
    ranked = select_best_entries(entries, limit=3, key=lambda entry: entry["n"])
    assert ranked == (
        {"n": 3, "tag": "a"},
        {"n": 3, "tag": "b"},
        {"n": 2, "tag": "c"},
    )


def test_sisgp_caps_work_experience_at_three_entries():
    text = _text(render_sisgp(_content(experience_count=5)))
    assert "Employer 4" in text  # most recent survives
    assert "Employer 0" not in text  # oldest is dropped
    assert sum(f"Employer {index}" in text for index in range(5)) == 3


def test_sisgp_renders_the_mandated_personal_fields():
    text = _text(render_sisgp(_content()))
    assert "Citizenship" in text
    assert "AZ" in text


def test_sisgp_renders_exactly_the_five_mandated_headings_in_order():
    # R-064: "you may not... create new categories or headings... will
    # render your application ineligible" -- this is the cheapest guard
    # against silently adding, dropping, or reordering a section.
    _assert_headings_in_order(_text(render_sisgp(_content())), _SISGP_HEADINGS)


def test_sisgp_date_of_birth_is_iso_not_localized():
    # R-079 mandates YYYY-MM-DD; USE_I18N=True + LANGUAGE_CODE="en-us" would
    # otherwise localize a `date` value to "May 4, 1999".
    text = _text(render_sisgp(_content()))
    assert "1999-05-04" in text
    assert "May" not in text


def test_sisgp_orders_education_reverse_chronologically():
    # R-078: reverse-chronological within every category, not just the
    # capped WORK EXPERIENCE.
    content = _content(
        education=(
            EducationEntry(
                degree_as_awarded="BSc",
                institution_original="Older University",
                city="Berlin",
                country="DE",
                start_date="2015-09-01",
            ),
            EducationEntry(
                degree_as_awarded="MSc",
                institution_original="Newer University",
                city="Berlin",
                country="DE",
                start_date="2020-09-01",
            ),
        )
    )
    text = _text(render_sisgp(content))
    assert text.index("Newer University") < text.index("Older University")


def test_sisgp_files_awards_under_scholarships_not_civic_engagement():
    # R-064 overrules the original brief here: presenting a scholarship as
    # civil-society engagement misdescribes it while leaving the heading it
    # actually belongs under blank.
    text = _text(render_sisgp(_content(awards=(AwardEntry(title="Fulbright Award"),))))
    civic_index = text.index("NETWORK/CIVIL SOCIETY ENGAGEMENT")
    scholarships_index = text.index("PREVIOUS SCHOLARSHIPS/AWARDS")
    award_index = text.index("Fulbright Award")
    assert scholarships_index < award_index
    assert not (civic_index < award_index < scholarships_index)


def test_rhodes_has_no_education_section():
    assert "Example University" not in _text(render_rhodes(_content()))


def test_rhodes_renders_exactly_the_six_mandated_headings_in_order():
    _assert_headings_in_order(_text(render_rhodes(_content())), _RHODES_HEADINGS)


def test_rhodes_sixth_section_renders_even_though_it_has_no_content_source():
    # Fixed numbering must survive an empty section -- deleting "6. Other"
    # would shift every later number, and there is no numbering left to
    # shift here, so this doubles as the empty-heading regression guard.
    assert "6. OTHER" in _text(render_rhodes(_content()))


def test_rhodes_routes_paid_and_unpaid_experience_to_their_own_sections():
    # R-080: paid work goes under section 1, unpaid under section 2. Distinct
    # employer names, not just distinct counts, so a bug that dumps
    # everything into one section can't slip past by accident.
    paid = ExperienceEntry(
        employer="Paid Employer",
        title="Role",
        city="Berlin",
        country="DE",
        start_date="2021-01-01",
        bullets=("desc",),
        unpaid=False,
    )
    unpaid = ExperienceEntry(
        employer="Unpaid Employer",
        title="Role",
        city="Berlin",
        country="DE",
        start_date="2021-01-01",
        bullets=("desc",),
        unpaid=True,
    )
    text = _text(render_rhodes(_content(experience=(paid, unpaid))))
    section1 = text[text.index("1. PROFESSIONAL") : text.index("2. VOLUNTEERING")]
    section2 = text[text.index("2. VOLUNTEERING") : text.index("3. PUBLICATIONS")]
    assert "Paid Employer" in section1
    assert "Unpaid Employer" not in section1
    assert "Unpaid Employer" in section2
    assert "Paid Employer" not in section2


def test_rhodes_publications_render_as_bare_titles():
    # R-080 requires publications to give author names, title and dates but
    # forbid an abstract. CVContent.publications is free text
    # (tuple[str, ...]) -- there is no structured author/title/date/abstract
    # split to check, so this only pins what the template actually does with
    # a publication string: print it verbatim under "Publications and
    # presentations", nothing added or stripped.
    # The upgrade path the earlier version of this test named -- a structured
    # PublicationEntry -- has been taken, so R-080's author/title/date
    # requirement is now a property of the schema rather than of whatever the
    # model wrote into a string. Rhodes keeps its single mandated section
    # (R-066 numbers it 3): the published/pending split belongs to the
    # standard layout, not to a funder's fixed form.
    publication = PublicationEntry(
        authors=("Doe, J.",),
        self_author_index=0,
        title="A Study of Something",
        venue="Journal of Examples",
        year=2024,
    )
    text = _text(render_rhodes(_content(publications=(publication,))))
    assert "Doe, J." in text
    assert "A Study of Something" in text
    assert "Journal of Examples" in text
    assert "2024" in text


def test_funder_template_without_an_id_is_a_caller_bug():
    with pytest.raises(ValueError):
        render_cv_with_warnings(_content(), variant="FUNDER_TEMPLATE")


def test_unknown_funder_template_id_is_a_caller_bug():
    with pytest.raises(ValueError):
        render_cv_with_warnings(_content(), variant="FUNDER_TEMPLATE", funder_template_id="NOPE")


def test_funder_template_dispatch_reaches_the_module():
    artifact, _violations = render_cv_with_warnings(
        _content(), variant="FUNDER_TEMPLATE", funder_template_id="SISGP"
    )
    assert artifact.variant == "FUNDER_TEMPLATE"
    assert "Citizenship" in _text(artifact)


def test_sisgp_routes_unpaid_work_to_civil_society_engagement():
    # R-064 mandates the NETWORK/CIVIL SOCIETY ENGAGEMENT heading; leaving it
    # blank while filing volunteering under WORK EXPERIENCE misdescribes the
    # entry and wastes the one section the funder asked for.
    paid = ExperienceEntry(
        employer="Azercell",
        title="Data Analyst",
        city="Baku",
        country="AZ",
        start_date="2023-08-01",
        bullets=("paid role",),
        unpaid=False,
    )
    unpaid = ExperienceEntry(
        employer="Coding Club",
        title="Volunteer Mentor",
        city="Baku",
        country="AZ",
        start_date="2022-02-01",
        bullets=("volunteer role",),
        unpaid=True,
    )
    text = _text(render_sisgp(_content(experience=(paid, unpaid))))
    work_index = text.index("WORK EXPERIENCE")
    civic_index = text.index("NETWORK/CIVIL SOCIETY ENGAGEMENT")
    assert work_index < text.index("Azercell") < civic_index
    assert civic_index < text.index("Coding Club")


def test_sisgp_cap_counts_only_paid_work():
    # R-078 caps WORK EXPERIENCE at three entries. Volunteering renders under a
    # different heading, so counting it against the cap would evict a paid role
    # in exchange for nothing.
    volunteering = tuple(
        ExperienceEntry(
            employer=f"Charity {index}",
            title="Volunteer",
            city="Berlin",
            country="DE",
            start_date=f"20{10 + index:02d}-01-01",
            bullets=(f"volunteering {index}",),
            unpaid=True,
        )
        for index in range(3)
    )
    text = _text(render_sisgp(_content(experience=_experience(3) + volunteering)))
    assert sum(f"Employer {index}" in text for index in range(3)) == 3
    assert sum(f"Charity {index}" in text for index in range(3)) == 3
