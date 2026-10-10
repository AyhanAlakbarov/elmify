import json
from datetime import date

import pytest
from pydantic import ValidationError

from apps.documents.schemas import (
    TIMELINE_STATEMENT_MAX,
    CVContent,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    PersonalInformation,
    PublicationEntry,
    PublicationStatus,
    SkillEntry,
    TimelineEntry,
)


def _minimal_content(**overrides):
    base = dict(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
        education=(
            EducationEntry(
                degree_as_awarded="Bachelor of Science",
                institution_original="Example University",
                city="Berlin",
                country="DE",
                start_date="2020-09-01",
                end_date="2024-06-30",
            ),
        ),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )
    base.update(overrides)
    return CVContent(**base)


def test_cv_content_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        CVContent(**{**_minimal_content().model_dump(mode="json"), "extra_field": "nope"})


def test_cv_content_photo_dob_sex_citizenship_optional_and_off_by_default():
    content = _minimal_content()
    assert content.personal_information.photo_url is None
    assert content.personal_information.date_of_birth is None
    assert content.personal_information.sex is None
    assert content.personal_information.citizenship is None


def test_cv_content_summary_optional_none_by_default():
    assert _minimal_content().summary is None


def test_cv_content_is_frozen():
    content = _minimal_content()
    with pytest.raises(ValidationError):
        content.document_language = "fr"


def test_email_must_look_like_an_email():
    with pytest.raises(ValidationError):
        PersonalInformation(full_name="Jane Doe", email="not-an-email")


def test_self_assessment_falls_back_to_the_overall_level():
    """One stated level fills the whole grid. A student who wrote "C1" said
    one thing; Europass asks for five, and their own level is the most
    conservative answer to all five."""
    entry = LanguageEntry(language="English", cefr_level="C1")
    assert entry.self_assessment == (
        ("Listening", "C1"),
        ("Reading", "C1"),
        ("Spoken interaction", "C1"),
        ("Spoken production", "C1"),
        ("Writing", "C1"),
    )


def test_an_explicit_sub_skill_overrides_the_fallback():
    """The reason the fields exist: a student refines one column after seeing
    the rendered CV, and only that column changes."""
    entry = LanguageEntry(language="English", cefr_level="C1", reading="C2", writing="B2")
    assert dict(entry.self_assessment) == {
        "Listening": "C1",
        "Reading": "C2",
        "Spoken interaction": "C1",
        "Spoken production": "C1",
        "Writing": "B2",
    }


def test_self_assessment_survives_a_language_with_no_stated_level():
    """cefr_level is optional today, so the grid must yield Nones, not raise."""
    entry = LanguageEntry(language="Azerbaijani")
    assert [level for _, level in entry.self_assessment] == [None] * 5


def test_sub_skills_default_to_none():
    entry = LanguageEntry(language="English", cefr_level="C1")
    assert entry.listening is None
    assert entry.writing is None


def test_mother_tongue_defaults_to_false():
    """False means "not stated", not "not their mother tongue". It sends the
    language under otherLanguages, which is accurate either way."""
    assert LanguageEntry(language="Azerbaijani").mother_tongue is False


def test_mother_tongue_can_be_set():
    entry = LanguageEntry(language="Azerbaijani", mother_tongue=True)
    assert entry.mother_tongue is True


def test_personal_information_link_fields_reject_non_https_schemes():
    # These become <a href> in a rendered PDF: a javascript:/data: URL there is
    # an injection vector, so the scheme is validated at the schema boundary.
    for url in ("javascript:alert(1)", "data:text/html,x", "http://example.com"):
        with pytest.raises(ValidationError):
            PersonalInformation(full_name="Jane", email="j@example.com", github_url=url)


def test_personal_information_rejects_a_malformed_orcid():
    with pytest.raises(ValidationError):
        PersonalInformation(full_name="Jane", email="j@example.com", orcid="0000-0002-1825")


def test_personal_information_links_show_the_address_when_no_handle_is_on_file():
    """No github_username or linkedin_handle here, so there is nothing to
    stand in for the address and the address is what shows."""
    personal = PersonalInformation(
        full_name="Jane",
        email="j@example.com",
        orcid="0000-0002-1825-0097",
        github_url="https://github.com/jane",
        linkedin_url="https://linkedin.com/in/jane",
        website_url="https://jane.example",
    )
    assert personal.links == (
        ("ORCID", "https://orcid.org/0000-0002-1825-0097", "orcid.org/0000-0002-1825-0097"),
        ("GitHub", "https://github.com/jane", "github.com/jane"),
        ("LinkedIn", "https://linkedin.com/in/jane", "linkedin.com/in/jane"),
        ("Website", "https://jane.example", "jane.example"),
    )


def test_personal_information_links_are_empty_when_none_are_set():
    assert PersonalInformation(full_name="Jane", email="j@example.com").links == ()


def test_orcid_x_checksum_is_accepted():
    personal = PersonalInformation(
        full_name="Jane", email="j@example.com", orcid="0000-0002-1825-009X"
    )
    assert personal.orcid == "0000-0002-1825-009X"


def _publication(**overrides):
    base = dict(authors=("Doe, J.", "Roe, R."), self_author_index=0, title="A Study")
    base.update(overrides)
    return PublicationEntry(**base)


def test_self_author_index_must_point_at_an_author():
    # Off-by-one here would bold a co-author's name as the applicant's own.
    with pytest.raises(ValidationError):
        _publication(self_author_index=2)


def test_self_author_index_is_optional_for_a_publication_the_applicant_did_not_write():
    assert _publication(self_author_index=None).self_author_index is None


def test_doi_is_stored_bare_not_as_a_url():
    with pytest.raises(ValidationError):
        _publication(doi="https://doi.org/10.1000/xyz")
    assert _publication(doi="10.1000/xyz").doi == "10.1000/xyz"


def test_a_publication_is_published_unless_it_says_otherwise():
    assert _publication().status is PublicationStatus.PUBLISHED
    assert _publication().status_label == ""


def test_published_and_pending_publications_are_strictly_separated():
    # S-011: a manuscript under review listed among published papers
    # overstates the record, so the split is a property of the content.
    published = _publication(title="Accepted", status=PublicationStatus.IN_PRESS)
    pending = _publication(title="Submitted", status=PublicationStatus.UNDER_REVIEW)
    drafted = _publication(title="Drafted", status=PublicationStatus.IN_PREPARATION)
    content = _minimal_content(publications=(pending, published, drafted))
    assert content.published_publications == (published,)
    assert content.pending_publications == (pending, drafted)
    assert pending.status_label == "under review"


def _experience(**overrides):
    base = dict(
        employer="Example Lab",
        title="Intern",
        city="Strasbourg",
        country="FR",
        start_date="2026-01-01",
        bullets=("Ran the data pipeline.",),
    )
    base.update(overrides)
    return ExperienceEntry(**base)


def test_an_experience_entry_needs_at_least_one_bullet():
    with pytest.raises(ValidationError):
        _experience(bullets=())


def test_bullets_are_capped_per_bullet_and_in_number():
    """500, raised from 300 -- see the Bullet cap's own comment for why."""
    with pytest.raises(ValidationError):
        _experience(bullets=("x" * 501,))
    with pytest.raises(ValidationError):
        _experience(bullets=tuple(f"bullet {index}" for index in range(13)))
    assert len(_experience(bullets=("x" * 500,)).bullets) == 1


def test_bullets_keep_their_order():
    entry = _experience(bullets=("First.", "Second.", "Third."))
    assert entry.bullets == ("First.", "Second.", "Third.")


def test_a_skill_category_is_optional():
    assert SkillEntry(name="Python").category is None
    assert SkillEntry(name="Python", category="Tools").category == "Tools"


def test_a_skill_needs_a_name():
    with pytest.raises(ValidationError):
        SkillEntry(name="")


def test_a_real_academic_cv_bullet_fits_without_being_split():
    """Verbatim from a measured CV: 337 characters, and it used to be split.

    At max_length=300 the extractor's only legal move on this line was to cut
    it in two, and character 300 lands inside "pruned" -- the rendered PDF
    carried "...successfully pr pr" and then a separate bullet beginning
    "uned 99%". The cap must accommodate a real bullet; brevity is a
    ConstraintRule's job, not a schema truncation's.
    """
    bullet = (
        "A map-agnostic framework that visualizes and navigates ultra-large chemical spaces "
        "(10B+ compounds) without requiring full molecular enumeration; this hierarchical "
        "atlas layout systematically improved local neighborhood resolution by up to 31% and "
        "powered a fast routing index that successfully pruned 99% of the similarity search "
        "space."
    )
    assert len(bullet) == 337
    entry = _experience(bullets=(bullet,))
    assert entry.bullets == (bullet,)
    assert "pruned" in entry.bullets[0]



def test_a_bare_handle_is_carried_and_never_turned_into_a_url():
    """S-013 wants GitHub in the header; a CV that prints a username had none.

    The *_url fields demand an https address and the extraction prompt refuses
    to build one from a username, because https://github.com/<username> points
    at whoever holds that name. So the handle is carried as text.
    """
    info = PersonalInformation(
        full_name="Jane Doe",
        email="jane@example.com",
        github_username="0rkhann",
        linkedin_handle="Jane Doe",
    )
    assert info.handles == (("GitHub", "0rkhann"), ("LinkedIn", "Jane Doe"))
    assert info.links == ()


def test_a_real_url_suppresses_the_bare_handle():
    """Both would say the same thing twice; the address is the better one."""
    info = PersonalInformation(
        full_name="Jane Doe",
        email="jane@example.com",
        github_url="https://github.com/0rkhann",
        github_username="0rkhann",
    )
    assert info.handles == ()
    assert info.links == (("GitHub", "https://github.com/0rkhann", "0rkhann"),)


def test_a_url_cannot_be_filed_as_a_handle():
    """The colon/slash exclusion is what keeps an address out of the text field."""
    with pytest.raises(ValidationError):
        PersonalInformation(
            full_name="Jane Doe",
            email="jane@example.com",
            github_username="https://github.com/0rkhann",
        )


def test_a_country_code_that_names_no_country_never_reaches_the_page():
    """"AA" passed ^[A-Z]{2}$ and reached a rendered CV as the literal "AA".

    country_name falls back to the code when it has no entry, so an invalid
    code does not fail loudly anywhere downstream -- it prints.

    It used to raise. Raising was measured as the largest cause of total
    extraction failure (2026-08-31 baseline), because a US CV that names no
    country made the model invent one and the invention failed the whole
    document. Dropped instead: the code still never reaches the page, and the
    empty field reaches the gap interview.
    """
    assert _experience(country="AA").country is None
    assert _experience(country="XX").country is None
    assert _experience(country="FR").country == "FR"


def test_a_date_outside_a_human_lifetime_is_dropped_rather_than_raised():
    """Measured: the extractor emitted 0944-09-01 and 0901-09-20 as the start
    of a bachelor's degree whose CV line reads "September 2020 - June 2024",
    in two of three runs off identical input. `date` accepted both, the ledger
    stored them, and generation carried them through unchanged -- a CV that
    reads "Sep 0944" and passes every verdict.

    This used to raise, and the raise was measured too: on a nine-document
    corpus 59% of extractions produced NOTHING, because one unreadable field
    fails the whole CVContent (2026-08-31 baseline). The bound is unchanged --
    a CV date outside 1900-2100 is a garbled token, not an unusual applicant --
    but the garbled token now costs its own field instead of the document, and
    the empty field reaches the gap interview.
    """
    assert _experience(start_date="0944-09-01").start_date is None
    assert _experience(start_date="2026-01-01", end_date="0901-09-20").end_date is None
    assert (
        PersonalInformation(
            full_name="Jane Doe", email="jane@example.com", date_of_birth="0999-01-01"
        ).date_of_birth
        is None
    )
    assert _experience(start_date="2026-01-01").start_date.year == 2026


def test_a_label_is_only_used_when_the_address_matches_it():
    """"GitHub: 0rkhann" pointing at evil.example is an assertion the reader
    cannot check. Before the labels existed the visible text WAS the address,
    so the destination was always on the page; the handle may only stand in
    where it hides nothing.
    """
    honest = PersonalInformation(
        full_name="Jane",
        email="j@example.com",
        github_url="https://github.com/jane",
        github_username="jane",
        linkedin_url="https://www.linkedin.com/in/jane",
        linkedin_handle="Jane Doe",
    )
    assert honest.links == (
        ("GitHub", "https://github.com/jane", "jane"),
        ("LinkedIn", "https://www.linkedin.com/in/jane", "Jane Doe"),
    )

    lying = honest.model_copy(
        update={
            "github_url": "https://evil.example/jane",
            "linkedin_url": "https://evil.example/in/jane",
        }
    )
    assert lying.links == (
        ("GitHub", "https://evil.example/jane", "evil.example/jane"),
        ("LinkedIn", "https://evil.example/in/jane", "evil.example/in/jane"),
    )


def test_a_lookalike_host_does_not_borrow_the_label():
    for url in (
        "https://github.com.evil.example/jane",
        "https://notgithub.com/jane",
        "https://evil.example/github.com/jane",
    ):
        info = PersonalInformation(
            full_name="Jane", email="j@example.com", github_url=url, github_username="jane"
        )
        assert info.links[0][2] != "jane", url


def test_a_subdomain_of_the_provider_still_counts():
    info = PersonalInformation(
        full_name="Jane",
        email="j@example.com",
        linkedin_url="https://www.linkedin.com/in/jane",
        linkedin_handle="Jane Doe",
    )
    assert info.links == (("LinkedIn", "https://www.linkedin.com/in/jane", "Jane Doe"),)


def test_a_website_shows_its_address_because_no_host_is_expected():
    info = PersonalInformation(
        full_name="Jane", email="j@example.com", website_url="https://jane.example/blog"
    )
    assert info.links == (("Website", "https://jane.example/blog", "jane.example/blog"),)


def test_content_stored_under_the_previous_schema_version_fails_on_the_version():
    """awards changed shape and CVDate bounded the date fields, both without a
    bump -- so version 2 meant two incompatible things and a stored draft
    failed confusingly on an award's type. It fails on its version now."""
    stored = {
        **_minimal_content().model_dump(mode="json"),
        "schema_version": 2,
        "awards": ["Best Thesis Award"],
    }
    with pytest.raises(ValidationError) as error:
        CVContent.model_validate(stored)
    assert "schema_version" in str(error.value)


def test_a_presentation_is_in_neither_publication_list():
    """S-011 keeps the publication record honest in one direction; this keeps
    it honest in the other -- a poster listed as a paper inflates it."""
    from apps.documents.schemas import PublicationEntry

    paper = PublicationEntry(authors=("Doe, J.",), title="A paper", year=2024)
    submitted = PublicationEntry(
        authors=("Doe, J.",), title="A draft", year=2025, status="UNDER_REVIEW"
    )
    poster = PublicationEntry(
        authors=("Doe, J.",), title="A poster", venue="IAC", year=2023, is_presentation=True
    )
    content = _minimal_content(publications=(paper, submitted, poster))
    assert content.published_publications == (paper,)
    assert content.pending_publications == (submitted,)
    assert content.presentations == (poster,)


def test_a_draft_stored_before_referees_existed_still_validates():
    """references is defaulted for exactly this reason: adding it must not be
    a fourth incompatible shape."""
    stored = _minimal_content().model_dump(mode="json")
    del stored["references"]
    assert CVContent.model_validate(stored).references == ()


class TestDatesArriveWritten:
    """The model copies the date as the page printed it; dates.py converts it.

    Measured cause: asked for a `date`, the extractor returned 0944-09-01 off
    text saying "September 2020" (2026-08-31 baseline, and 2026-08-30 before
    it). Copying is an easier job than converting, and the copy is checkable
    against the page in a way an ISO date never was.
    """

    def _education(self, **overrides):
        return {
            "degree_as_awarded": "BSc",
            "institution_original": "Example University",
            "city": "Berlin",
            "country": "DE",
            **overrides,
        }

    def test_a_written_start_date_is_read(self):
        entry = EducationEntry.model_validate(self._education(start_date="September 2020"))
        assert entry.start_date == date(2020, 9, 1)

    def test_an_end_date_resolves_to_the_end_of_what_it_names(self):
        entry = EducationEntry.model_validate(
            self._education(start_date="2020", end_date="2024")
        )
        assert entry.start_date == date(2020, 1, 1)
        assert entry.end_date == date(2024, 12, 31)

    def test_a_garbled_year_becomes_no_date_rather_than_a_wrong_one(self):
        """0944 was emitted twice in three runs off "September 2020". Before
        this it raised and took the whole document with it; now the field is
        empty and the gap interview asks."""
        entry = EducationEntry.model_validate(self._education(start_date="0944-09-01"))
        assert entry.start_date is None

    def test_a_degree_with_no_dates_at_all_still_validates(self):
        """A required field the document does not state is what made 59% of
        real CVs extract to nothing."""
        entry = EducationEntry.model_validate(self._education())
        assert entry.start_date is None and entry.end_date is None


class TestAPlaceTheDocumentNeverStated:
    """The largest single cause of total extraction failure, measured.

    A US academic CV prints "Philadelphia, PA" and never names a country,
    because every reader knows it. country was required, so the model had to
    emit something and emitted 'NY', 'CT', 'MA', 'UK', 'UQ', 'TQ', 'EJ', 'AA'.
    CountryCode refused them and took the whole document down: 59% of runs
    over nine documents produced no facts at all (2026-08-31 baseline), and
    after the date fix every remaining failure was this field.
    """

    def _education(self, **overrides):
        return {
            "degree_as_awarded": "BSc",
            "institution_original": "Example University",
            **overrides,
        }

    def test_a_degree_with_no_place_at_all_still_validates(self):
        entry = EducationEntry.model_validate(self._education())
        assert entry.city is None and entry.country is None

    def test_a_code_that_names_no_country_is_dropped_rather_than_raised(self):
        for written in ("NY", "CT", "UQ", "TQ", "EJ", "AA", "HQ", "PZ", "XX"):
            entry = EducationEntry.model_validate(self._education(country=written))
            assert entry.country is None, written

    def test_uk_is_read_as_gb(self):
        """Reserved in ISO 3166-1 for the United Kingdom and unambiguous, and
        it was emitted twice across the corpus."""
        assert EducationEntry.model_validate(self._education(country="UK")).country == "GB"

    def test_a_lowercase_code_is_still_that_country(self):
        assert EducationEntry.model_validate(self._education(country="de")).country == "DE"

    def test_a_real_code_is_untouched(self):
        assert EducationEntry.model_validate(self._education(country="TR")).country == "TR"

    def test_a_blank_city_is_no_city(self):
        """Measured: given nothing to say, the model emits whitespace to satisfy
        min_length rather than leaving the field out."""
        assert EducationEntry.model_validate(self._education(city="   ")).city is None


class TestTheModelIsAskedForWhatThePageSays:
    """Measured (2026-08-31 accuracy run): dates scored 53% while entries
    scored 100%, and the cause was a contradiction we shipped. The JSON schema
    said `"format": "date"` -- ISO only -- while the prompt said "copy the date
    exactly as the document prints it". The model obeyed the schema, and where
    it could not produce ISO it emitted null: every date on a CV writing
    "15/09/2014" or "June - Aug 2025" came back empty, and parse_cv_date never
    saw the string it exists to read.
    """

    def test_a_date_field_is_a_plain_string_to_the_model(self):
        for model in (EducationEntry, ExperienceEntry):
            schema = model.model_json_schema()["properties"]["start_date"]
            assert "date" not in json.dumps(schema), model.__name__

    def test_a_date_the_page_wrote_its_own_way_is_read(self):
        entry = EducationEntry.model_validate(
            {
                "degree_as_awarded": "Lisans",
                "institution_original": "Bogazici Universitesi",
                "start_date": "15/09/2014",
                "end_date": "30/06/2018",
            }
        )
        assert entry.start_date == date(2014, 9, 15)
        assert entry.end_date == date(2018, 6, 30)


class TestARangeStatesItsYearOnce:
    """"June - Aug 2025" is one range and one year. Parsed separately the start
    has no year at all, which is how six dates on the Harvard engineering
    résumé came back empty in both runs."""

    def _experience_entry(self, start, end):
        return ExperienceEntry.model_validate(
            {
                "employer": "Example Lab",
                "title": "Research Assistant",
                "bullets": ["Did the work."],
                "start_date": start,
                "end_date": end,
            }
        )

    def test_the_start_borrows_the_year_the_end_states(self):
        entry = self._experience_entry("June", "Aug 2025")
        assert entry.start_date == date(2025, 6, 1)
        assert entry.end_date == date(2025, 8, 31)

    def test_a_start_that_states_its_own_year_is_untouched(self):
        entry = self._experience_entry("June 2023", "Aug 2025")
        assert entry.start_date == date(2023, 6, 1)

    def test_an_end_with_no_year_stays_empty(self):
        """"September 2020 - June" gives June of no stated year: 2021 is a
        guess, and the gap interview asks rather than the parser inventing."""
        entry = self._experience_entry("September 2020", "June")
        assert entry.start_date == date(2020, 9, 1)
        assert entry.end_date is None


def test_an_experience_entry_project_is_optional_and_separate_from_the_title():
    """S-037: the role is the title and the project is what it worked on. With
    one field the extractor copied the source CV's own separators into the
    bold role line -- ", Project Title:" in one entry, "| Project Title:" in
    the next."""
    entry = ExperienceEntry(
        employer="EPFL",
        title="Research Intern",
        project="Generative AI for peptide organocatalyst design",
        bullets=("Benchmarked generative frameworks.",),
    )
    assert entry.title == "Research Intern"
    assert entry.project == "Generative AI for peptide organocatalyst design"
    assert ExperienceEntry(employer="EPFL", title="Intern", bullets=("x",)).project is None


def test_a_bullet_closes_the_space_a_text_layer_opened_inside_brackets():
    """Measured: pypdf read "(PMe3)" as "(PMe 3)" and the model moved the space
    to "( PMe3)", which is what the rendered CV printed. "Python 3" is left
    alone: only the gap directly inside a bracket is closed."""
    entry = ExperienceEntry(
        employer="ICIQ",
        title="Summer Fellowship",
        bullets=("Modeled variable phosphine ( PMe3 ) concentrations in Python 3",),
    )
    assert entry.bullets == ("Modeled variable phosphine (PMe3) concentrations in Python 3",)


def test_a_group_named_after_its_investigator_does_not_print_them_twice():
    """Measured on the real CV the moment `group` existed: it names a group AS
    its PI -- "EPFL | Prof. Philippe Schwaller's group" -- so the entry rendered
    "Prof. Philippe Schwaller's group, EPFL - Supervisor: Prof. Philippe
    Schwaller". S-028 asks for both because most CVs name a laboratory; where
    the document names the person, they are one fact."""
    named = ExperienceEntry(
        employer="EPFL",
        title="Research Intern",
        group="Prof. Philippe Schwaller's group",
        supervisor="Prof. Philippe Schwaller",
        bullets=("Benchmarked frameworks.",),
    )
    assert named.distinct_supervisor is None

    lab = named.model_copy(update={"group": "Laboratory of Artificial Chemical Intelligence"})
    assert lab.distinct_supervisor == "Prof. Philippe Schwaller"

    # No group at all, and no supervisor at all: both pass straight through.
    no_group = named.model_copy(update={"group": None})
    assert no_group.distinct_supervisor == "Prof. Philippe Schwaller"
    assert named.model_copy(update={"supervisor": None}).distinct_supervisor is None


def test_an_education_entry_holds_its_medium_of_instruction():
    """S-050: a degree taught in English can stand in for a language test at
    several destinations. The field records what language it was TAUGHT in,
    never what language the document is written in."""
    entry = EducationEntry(
        degree_as_awarded="BSc Chemical Engineering",
        institution_original="ADA University",
        medium_of_instruction="English",
    )

    assert entry.medium_of_instruction == "English"


def test_a_timeline_entry_carries_a_span_and_one_statement():
    entry = TimelineEntry(
        start_date="June 2023",
        end_date="November 2023",
        statement="Full-time carer for a family member.",
    )

    assert entry.start_date == date(2023, 6, 1)
    assert entry.end_date == date(2023, 11, 30)
    assert entry.statement == "Full-time carer for a family member."


def test_a_timeline_entry_refuses_an_empty_statement():
    with pytest.raises(ValidationError):
        TimelineEntry(start_date="2023-06-30", end_date="2023-11-01", statement="")


def test_a_timeline_entry_refuses_a_statement_over_the_cap():
    with pytest.raises(ValidationError):
        TimelineEntry(
            start_date="2023-06-30",
            end_date="2023-11-01",
            statement="x" * (TIMELINE_STATEMENT_MAX + 1),
        )


def test_cv_content_has_no_timeline_by_default():
    assert _minimal_content().timeline == ()
