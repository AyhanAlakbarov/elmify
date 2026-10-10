from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
    model_validator,
)

from apps.reference_data import ISO_3166_ALPHA2_CODES

from .dates import carry_year, parse_cv_date, parse_end_date

_CONTENT_CONFIG = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


#: Reserved in ISO 3166-1 for the United Kingdom, and emitted twice across the
#: 2026-08-31 corpus. Unambiguous, so it is read rather than dropped. US state
#: codes are NOT mapped: "CA" is California and also Canada, and a table that
#: silently resolved that would put a Los Angeles degree in Ontario.
_COUNTRY_ALIASES = {"UK": "GB"}


def _known_country(value: object) -> str | None:
    """A real country, or nothing at all.

    Measured, and the largest single cause of total extraction failure: a US
    academic CV prints "Philadelphia, PA" and never names a country, so a
    required field forced the model to invent one -- 'NY', 'CT', 'MA', 'UQ',
    'TQ', 'EJ', 'AA', 'HQ', 'PZ'. This used to raise, which failed the whole
    CVContent and wrote no facts at all: 59% of runs over nine documents
    (2026-08-31 baseline). Dropping the field costs a country; raising cost
    the CV.

    An empty country reaches the gap interview, which asks. Note what still
    catches nothing: a code naming the WRONG country ("BA" for Strasbourg,
    measured). A security review of this branch found the claim that
    verification.py catches it to be false, and it was repeated here from an
    older comment -- verification._details_conflict compares a CLAIM's country
    against the LEDGER FACT's, so it sees generation drifting from the ledger
    and has never known where Strasbourg is. Nothing in this codebase does.
    """
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    code = _COUNTRY_ALIASES.get(code, code)
    return code if code in ISO_3166_ALPHA2_CODES else None


CountryCode = Annotated[str | None, BeforeValidator(_known_country)]


def _stated(value: object) -> str | None:
    """Whitespace is not a statement.

    Measured: given nothing to say and a min_length to satisfy, the model
    emits " " rather than leaving the field out.
    """
    if not isinstance(value, str):
        return None
    return value.strip() or None


#: A date as the CV printed it -- "September 2020", "WS 2020/21", "01.09.2020"
#: -- converted by apps/documents/dates.py rather than by the model.
#:
#: Measured twice. From "September 2020 - June 2024" the extractor emitted
#: start_date 0944-09-01 in one run and 0901-09-20 in another (2026-08-30), and
#: 0200-01-01, 0527-01-01 and 0820-01-01 across a nine-document corpus
#: (2026-08-31). Both parse as dates, so nothing downstream objected: the
#: ledger stored one and the generated CV printed "Sep 0944" with 0 UNSUPPORTED
#: verdicts. The model exposes no temperature, top_p or seed (all rejected by
#: the API) and higher reasoning effort made it worse, so this cannot be tuned
#: away -- it has to stop being the model's job.
#:
#: Unreadable is None, not a raise. Raising was the old behaviour and it cost
#: the whole document: on the 2026-08-31 corpus 59% of extractions produced
#: nothing at all, because one bad field fails the entire CVContent. A null
#: field reaches the gap interview, which asks the student.
#: WithJsonSchema is load-bearing, not decoration. Without it pydantic tells
#: the model `"format": "date"` -- ISO only -- while the prompt tells it to
#: copy the date as printed, and the model obeys the schema: every date on a
#: CV writing "15/09/2014" or "June - Aug 2025" came back null, because null
#: was the only legal answer. Measured at 53% date accuracy against 100% entry
#: accuracy (2026-08-31). The Python type is unchanged; only what the model is
#: asked for changes.
_AS_WRITTEN = WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "null"}]})

CVDate = Annotated[date | None, BeforeValidator(parse_cv_date), _AS_WRITTEN]

#: The far end of a range. "Fall 2020" as an end is November, not September,
#: and a bare "2024" is 31 December -- so "Fall 2020 - Spring 2022" covers what
#: it says instead of stopping two months short.
CVEndDate = Annotated[date | None, BeforeValidator(parse_end_date), _AS_WRITTEN]

# Deliberately not pydantic.EmailStr: that pulls in email-validator, a
# dependency this project does not have, for one field on one schema.
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

# S-013 (docs/research/cv-style-rules.csv) puts ORCID and, where relevant,
# GitHub/Scholar/a personal site in the contact header as live links. https
# only, and no whitespace or angle brackets: these become <a href> in a
# rendered PDF, so the scheme is a trust boundary -- a javascript: or data:
# URL in a PDF annotation is an injection vector, not a link.
_HTTPS_URL_PATTERN = r'^https://[^\s<>"]+$'
# ORCID's own checksummed form; the final digit may be X.
_ORCID_PATTERN = r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$"


def _anchor_text(url: str, handle: str | None, expected_host: str | None) -> str:
    """The handle, but only when the address really is the provider the label
    names; otherwise the address itself, minus its scheme.

    A label is an assertion about where a link goes, and "GitHub: 0rkhann"
    pointing at an unrelated host is one the reader cannot check. Before the
    labels existed the visible text WAS the address, so the destination was
    always on the page -- the handle may stand in only where it hides nothing.
    Note the dot in the suffix test: "github.com.evil.example" is not GitHub,
    and a bare endswith would say it was.
    """
    host = (urlsplit(url).hostname or "").lower()
    if handle and expected_host and (host == expected_host or host.endswith(f".{expected_host}")):
        return handle
    return url.removeprefix("https://").rstrip("/")


class PersonalInformation(BaseModel):
    model_config = _CONTENT_CONFIG

    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320, pattern=_EMAIL_PATTERN)
    phone: str | None = Field(default=None, max_length=30)
    photo_url: str | None = None
    date_of_birth: CVDate = None
    # SISGP (R-079) mandates both as fixed template fields; every other
    # variant leaves them unset and never renders them.
    sex: str | None = Field(default=None, max_length=30)
    citizenship: str | None = Field(default=None, max_length=100)
    # S-013. Stored as the bare identifier, not a URL, because the rule wants
    # "orcid.org/0000-..." as the *visible* text -- the template builds the
    # href from it, so the displayed form cannot drift from the target.
    orcid: str | None = Field(default=None, pattern=_ORCID_PATTERN)
    linkedin_url: str | None = Field(default=None, max_length=200, pattern=_HTTPS_URL_PATTERN)
    github_url: str | None = Field(default=None, max_length=200, pattern=_HTTPS_URL_PATTERN)
    # A Scholar profile, ResearchGate, or a personal page are all just a URL
    # and land here; there is one field rather than one per platform until a
    # CV needs two of them at once.
    website_url: str | None = Field(default=None, max_length=200, pattern=_HTTPS_URL_PATTERN)
    #: What the document printed when it printed a handle rather than an
    #: address -- "Github: 0rkhann", "LinkedIn: Orkhan Abdullayev". S-013 wants
    #: GitHub in the contact header, and before these existed such a CV lost it
    #: entirely: the *_url fields demand an https address and the extraction
    #: prompt rightly refuses to build one from a username, because
    #: https://github.com/<username> points at whoever holds that name. The
    #: colon/slash exclusion keeps a URL from being filed here as text.
    github_username: str | None = Field(default=None, max_length=100, pattern=r"^[^:/]+$")
    linkedin_handle: str | None = Field(default=None, max_length=100, pattern=r"^[^:/]+$")

    @property
    def handles(self) -> tuple[tuple[str, str], ...]:
        """(label, handle) for the contact header, printed verbatim and never linked.

        Suppressed when the real URL is on file: that is the better rendering
        of the two, and printing both would say the same thing twice.
        """
        pairs = []
        if self.github_username and not self.github_url:
            pairs.append(("GitHub", self.github_username))
        if self.linkedin_handle and not self.linkedin_url:
            pairs.append(("LinkedIn", self.linkedin_handle))
        return tuple(pairs)

    @property
    def links(self) -> tuple[tuple[str, str, str], ...]:
        """(label, href, visible text) for the contact header, in a fixed order.

        Carried as a property for the same reason as
        ``LanguageEntry.self_assessment``: the templates stay a loop, and the
        orcid.org address is built in one place instead of in each of them.

        The anchor text is the handle, not the address -- "LinkedIn: Orkhan
        Abdullayev", not a 47-character profile URL that wraps.

        S-013 says the opposite ("URL text readable ... not buried in anchor
        text") and S-013 is the outlier. Section508.gov, WCAG.com, Yale
        Usability, UC and Level Access all state the rule the other way round:
        never use a URL as link text, because a screen-reader user tabbing
        through links in isolation gets a protocol and a path instead of a
        destination. S-013 is one university researcher page; the accessibility
        standards are the ones with a conformance target behind them.

        The real cost is print: a paper copy, or a viewer that strips
        annotations, loses the address. That is a genuine trade and the reason
        S-013 exists -- it is just not the stronger argument.

        ORCID keeps its address as the text: the identifier IS the readable
        thing there, and S-013 names that case specifically.
        """
        links = (
            [("ORCID", f"https://orcid.org/{self.orcid}", f"orcid.org/{self.orcid}")]
            if self.orcid
            else []
        )
        # The handle fields, when the document printed one, are exactly the
        # anchor text wanted here.
        for label, url, handle, expected_host in (
            ("GitHub", self.github_url, self.github_username, "github.com"),
            ("LinkedIn", self.linkedin_url, self.linkedin_handle, "linkedin.com"),
            # No expected host, so no handle field either: a personal site
            # always shows its own address.
            ("Website", self.website_url, None, None),
        ):
            if url:
                links.append((label, url, _anchor_text(url, handle, expected_host)))
        return tuple(links)


#: One achievement line. S-010 wants short active-verb bullets, so the cap is
#: per bullet rather than on a single prose blob.
#:
#: Raised from 300, which was too small for a real academic CV and was
#: destroying content rather than constraining style. Two bullets on a
#: measured CV run 337 and 321 characters; asked for a 337-character line in a
#: 300-character field, the extractor split it into TWO bullets at exactly the
#: boundary -- mid-word, because character 300 of that line falls inside
#: "pruned" and inside "optimization". The rendered PDF showed
#: "...successfully pr pr" followed by a fresh bullet "uned 99% of the
#: similarity search space." A cap that makes a model mutilate a word is worse
#: than a long bullet: the model has no legal move except to split, drop or
#: reword, and two of those three are content loss.
#:
#: 500 is ~1.5x the longest measured real bullet. It bounds nothing that was
#: not already bounded -- _MAX_TEXT_CHARS caps the whole input document at
#: 40,000 characters, and bullets/experience cap the counts at 12 and 30. If
#: S-010's brevity should be *enforced* rather than merely preferred, that
#: belongs in a ConstraintRule, which can flag a long bullet for a human;
#: a schema cap can only silently corrupt it.
def _tidy_prose(value: object) -> object:
    """Close the gap a PDF text layer opens inside brackets.

    Measured: pypdf reads "(PMe3)" with a subscript 3 as "(PMe 3)", and the
    model, told to copy, moved the space rather than dropping it -- the
    rendered CV printed "( PMe3)". No prose puts a space directly inside a
    bracket, so closing it is safe; the subscript gap itself is not, because
    "Python 3" is real.
    """
    if not isinstance(value, str):
        return value
    return re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", value))


Bullet = Annotated[
    str, BeforeValidator(_tidy_prose), StringConstraints(min_length=1, max_length=500)
]


class _RangeEntry(BaseModel):
    """An entry whose two dates are the ends of one range.

    The year lives on whichever end printed it, so the two cannot be parsed
    independently -- and pydantic hands a field validator one value with no
    siblings, which is why this is a model validator and not part of CVDate.
    """

    @model_validator(mode="before")
    @classmethod
    def _carry_range_year(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        carried = carry_year(data.get("start_date"), data.get("end_date"))
        return data if carried is data.get("start_date") else {**data, "start_date": carried}


class EducationEntry(_RangeEntry):
    model_config = _CONTENT_CONFIG

    degree_as_awarded: str = Field(min_length=1, max_length=200)
    degree_english: str | None = Field(default=None, max_length=200)
    institution_original: str = Field(min_length=1, max_length=300)
    institution_english: str | None = Field(default=None, max_length=300)
    city: Annotated[str | None, BeforeValidator(_stated)] = Field(default=None, max_length=200)
    country: CountryCode = None
    start_date: CVDate = None
    end_date: CVEndDate = None
    grade_native: str | None = Field(default=None, max_length=50)
    grade_scale: str | None = Field(default=None, max_length=100)
    grade_conversion: str | None = Field(default=None, max_length=100)
    ects_credits: int | None = Field(default=None, ge=0, le=1000)
    #: The degree's own thesis, printed under the degree. Every source that
    #: discusses graduate-applicant CVs puts the two together: the education
    #: block is the first landmark a reader's eye hits and the thesis is the
    #: most informative fact in it. Duplicating ResearchEntry.thesis_title is
    #: the point -- the Research section carries the work, this carries the
    #: qualification it was submitted for -- and it stays null unless the
    #: document states a thesis for that degree.
    thesis_title: str | None = Field(default=None, max_length=300)
    #: "3rd of 120", "top 5%". A string, not a number: what a transcript
    #: states is a rank, a percentile or a decile depending on the country,
    #: and US credential guidance calls it more telling than a converted GPA.
    class_rank: str | None = Field(default=None, max_length=100)
    #: Who supervised the thesis above. UCC lists it among the things an
    #: education entry carries -- "dates, qualification, supervisor,
    #: dissertation, papers and awards" -- and Toronto's worked CV prints
    #: "Dissertation: ..." then "Supervisor: Dr. Carine Mendelsson" under the
    #: degree. We printed the thesis and had nowhere to name who supervised it.
    #: Distinct from ExperienceEntry.supervisor, which supervises a POST.
    supervisor: str | None = Field(default=None, max_length=200)
    #: What paid for the degree, as the document states it. UCC's worked CV
    #: prints "Funded by the Irish Research Council for Humanities and Social
    #: Sciences" as a line of the degree, which is where a funded degree names
    #: its funder; the award itself still belongs in `awards`.
    funding: str | None = Field(default=None, max_length=300)
    #: R-028 ("little research output: add research-relevant coursework") and
    #: S-029 (the discipline switcher's main lever: the degree title is stated
    #: honestly and the adjustment is in the supporting detail). R-028 has been
    #: in the catalog since the first research pass with no field able to
    #: satisfy it. One string, as the CV lists them -- not a tuple, because a
    #: module list is punctuated prose on every CV measured and splitting it
    #: invites the model to invent boundaries.
    relevant_coursework: str | None = Field(default=None, max_length=1_000)
    #: The language the degree was TAUGHT in, as the institution states it --
    #: not the language the document is written in. S-050, sourced to Cornell,
    #: USC, BU and ASU (and R-065): a degree taught in English can stand in for
    #: a language certificate, and the conditions differ at every destination --
    #: USC also requires the country's only official language to be English, BU
    #: requires the transcript to say it was the SOLE language of instruction.
    #:
    #: So this holds the FACT and nothing decides anything from it here. The
    #: waiver is a per-destination rule and belongs to the programme layer;
    #: gathering it is the standard layer's job (design, "Scope: this is the
    #: STANDARD layer"). Nothing prints it today either -- whether a CV should
    #: carry the line at all, or only the application form, is a render
    #: decision nobody has taken.
    medium_of_instruction: str | None = Field(default=None, max_length=200)


class ExperienceEntry(_RangeEntry):
    model_config = _CONTENT_CONFIG

    employer: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=200)
    #: The thesis or project the post worked on, as the document names it --
    #: "Project Title: AZIMUTH: Hierarchical GTM ..." minus the label. Null for
    #: an ordinary job. Before this field existed the extractor had one place
    #: to put that name, so `title` came out as "Research Intern, Project
    #: Title: Generative AI for ..." in one entry and "Summer Fellowship |
    #: Project Title: ..." in the next -- the source CV's own two separators,
    #: copied verbatim -- and the bold role line wrapped onto two lines with
    #: the employer stranded under it (S-037). The role is the title; this is
    #: what the role worked on.
    project: str | None = Field(default=None, max_length=300)
    #: A research position is both a post and a project, and until this field
    #: existed neither bucket could hold one: `research` has no employer,
    #: title or bullets, and `experience` had no supervisor. Applicants with
    #: several posts in academic groups were therefore split across two
    #: headings -- one under Research, the rest under Experience -- with
    #: Publications rendered between them. Null for an ordinary job.
    supervisor: str | None = Field(default=None, max_length=200)
    #: The laboratory, group or department inside the employer. S-028 requires
    #: an academic post to name "the group or laboratory and its principal
    #: investigator"; `employer` holds "EPFL" and the rest was lost. The
    #: applicant's own CV wrote it as "EPFL | Prof. Schwaller's group", and
    #: Toronto's research sample as "Department of Industrial Engineering,
    #: University of Toronto". Null for an ordinary job.
    group: str | None = Field(default=None, max_length=300)
    #: Optional, and measured: a real CV names the employer but not the town
    #: for four roles in five. Required, these forced the extractor to choose
    #: between inventing a location from world knowledge ("EPFL is in
    #: Lausanne" is not something the document said) and emitting whitespace
    #: to satisfy min_length -- it chose whitespace, and ingestion of the
    #: whole CV failed on string_too_short. ResearchEntry already treats its
    #: location this way; this is the same rule for the same reason.
    city: Annotated[str | None, BeforeValidator(_stated)] = Field(default=None, max_length=200)
    country: CountryCode = None
    start_date: CVDate = None
    end_date: CVEndDate = None
    # S-010: experience entries are bullets (active verbs, no pronouns), not a
    # prose block -- a single string flattens real structure into a paragraph
    # and the reader loses the scan. Research entries keep prose, which the
    # same rule allows for a specialist reader.
    bullets: tuple[Bullet, ...] = Field(min_length=1, max_length=12)
    # Rhodes (R-080) routes paid work to section 1 and unpaid/voluntary work
    # to section 2 -- every other variant ignores this field. Defaults False
    # (paid) so existing construction and _PAYLOAD_KEYS/verification, which
    # never read it, are unaffected.
    unpaid: bool = False

    @property
    def distinct_supervisor(self) -> str | None:
        """The supervisor, unless the group already names them.

        Measured on the real CV the moment `group` existed: it writes a group
        AS its PI -- "EPFL | Prof. Philippe Schwaller's group" -- so the two
        fields hold one fact, and the entry rendered "Prof. Philippe
        Schwaller's group, EPFL -- Supervisor: Prof. Philippe Schwaller".
        S-028 asks for the group AND the investigator because most CVs name a
        laboratory ("Department of Industrial Engineering"); where the document
        names the person instead, printing both says the same thing twice.

        Same shape and same reason as PersonalInformation.handles, which
        suppresses a handle when the real URL is on file.

        Matched on the SURNAME -- the last word of the supervisor's name, which
        is what a group is named after -- so "Prof. Philippe Schwaller" is
        suppressed by "Prof. Philippe Schwaller's group" and by "Schwaller
        lab" alike. Display only: render._section_order reads `supervisor`
        itself, and a suppressed one still means this is an academic post.
        """
        if not self.supervisor or not self.group:
            return self.supervisor
        words = [word for word in re.findall(r"[^\W\d_]+", self.supervisor, re.UNICODE) if word]
        surname = words[-1] if words else ""
        if surname and re.search(rf"\b{re.escape(surname)}\b", self.group, re.IGNORECASE):
            return None
        return self.supervisor


class PublicationStatus(StrEnum):
    """S-011 keeps published work strictly separated from work that is not
    published yet; the status is what the separation is drawn from."""

    PUBLISHED = "PUBLISHED"
    IN_PRESS = "IN_PRESS"
    UNDER_REVIEW = "UNDER_REVIEW"
    IN_PREPARATION = "IN_PREPARATION"


_STATUS_LABELS: dict[str, str] = {
    PublicationStatus.IN_PRESS: "in press",
    PublicationStatus.UNDER_REVIEW: "under review",
    PublicationStatus.IN_PREPARATION: "in preparation",
}


class PublicationEntry(BaseModel):
    """One citation, held as fields rather than as a pre-formatted string.

    S-011 asks for the applicant's own name bolded, author order preserved, one
    citation style applied consistently, and a resolvable DOI. None of that is
    reachable from a string: the render path would have to find a name inside
    it, and "Abdullayev O.", "O. Abdullayev" and "Abdullayev, Orkhan" are the
    same person while a co-author's similar surname is not. The applicant is
    identified by position instead, which is exact.
    """

    model_config = _CONTENT_CONFIG

    #: In the order the byline prints them -- author order is itself a claim.
    authors: tuple[str, ...] = Field(min_length=1, max_length=50)
    self_author_index: int | None = Field(default=None, ge=0)
    title: str = Field(min_length=1, max_length=300)
    #: Journal, conference or publisher.
    venue: str | None = Field(default=None, max_length=300)
    year: int | None = Field(default=None, ge=1900, le=2100)
    #: Volume, issue and page range exactly as the registry deposited them.
    #: Strings rather than ints: an issue is "6", but also "S1", "3-4" or
    #: "Suppl 2", and a page range is "4739-4745" or "e0123456". Held so a
    #: citation can print the locator instead of a placeholder -- the CV this
    #: was validated against renders its own issue number as "XXX".
    volume: str | None = Field(default=None, max_length=20)
    issue: str | None = Field(default=None, max_length=20)
    pages: str | None = Field(default=None, max_length=40)
    #: The bare DOI (10.xxxx/yyyy); the template builds the resolvable link, so
    #: the printed form and the target cannot drift apart.
    doi: str | None = Field(default=None, max_length=200, pattern=r"^10\.\d{4,9}/\S+$")
    #: The landing page, for an item that has no DOI. Measured on a real CV:
    #: the IAC proceedings paper has no DOI and its address
    #: (dl.iafastro.directory/event/IAC-2023/paper/76798/) sits in the source
    #: PDF's link annotations, which extract_link_urls now recovers -- and this
    #: model could not hold it, so the citation rendered bare. https only, like
    #: every other URL on this schema, and the renderer is what suppresses it
    #: where a funder forbids hyperlinks (R-017, Fulbright).
    url: str | None = Field(default=None, max_length=300, pattern=_HTTPS_URL_PATTERN)
    status: PublicationStatus = PublicationStatus.PUBLISHED
    #: A conference talk or poster rather than a paper. Its own section, not
    #: its own model: a presentation is a byline, a title, a venue and a year
    #: -- exactly this shape -- and merging the two lists either inflates the
    #: publication record or hides the presentations. `venue` holds the
    #: conference; PublicationStatus does not apply and stays at its default.
    is_presentation: bool = False

    @model_validator(mode="after")
    def _self_author_index_within_authors(self) -> PublicationEntry:
        if self.self_author_index is not None and self.self_author_index >= len(self.authors):
            raise ValueError("self_author_index does not point at one of the authors")
        return self

    @property
    def byline_suffix(self) -> str:
        """What separates the author list from the title.

        One period, never two: a byline ending in an initial ("Roe, R.")
        already carries one, and "Roe, R.. Transfer learning" is the kind of
        detail S-011's "flawlessly consistent" is about.
        """
        if self.year:
            return f" ({self.year})."
        return "" if self.authors[-1].endswith(".") else "."

    @property
    def status_label(self) -> str:
        """Empty for published work, so the template prints no bracket at all."""
        return _STATUS_LABELS.get(self.status, "")


class ResearchEntry(_RangeEntry):
    model_config = _CONTENT_CONFIG

    thesis_title: str = Field(min_length=1, max_length=300)
    supervisor: str | None = Field(default=None, max_length=200)
    # Where and when the work was done. Optional, unlike education and
    # experience, because a CV that does not state a thesis date must not
    # acquire one here -- an absent field renders as nothing, and inventing a
    # plausible one is the failure this engine exists to prevent.
    institution: str | None = Field(default=None, max_length=300)
    city: Annotated[str | None, BeforeValidator(_stated)] = Field(default=None, max_length=200)
    country: CountryCode = None
    start_date: CVDate = None
    end_date: CVEndDate = None
    methods: str | None = Field(default=None, max_length=1_000)
    outcomes: str | None = Field(default=None, max_length=1_000)
    #: What paid for the work. UCC's worked CV prints the funder on the project
    #: line of every research entry -- 'Project: "..." - Funded by Health
    #: Research Board'. Same field name and same role as EducationEntry.funding.
    funding: str | None = Field(default=None, max_length=300)


class AwardEntry(BaseModel):
    """One honour, prize or fellowship.

    A model, not a bare string, because the date has to be a field before
    anything can right-align it or abbreviate its month -- as a string the
    date lived inside the title ("... - November 2023") and awards were the
    one dated section formatting its own dates. Optional: a CV that states no
    date for an award must not acquire one, same rule as ResearchEntry's.
    """

    model_config = _CONTENT_CONFIG

    title: str = Field(min_length=1, max_length=300)
    date: CVDate = None
    #: The faculty, institution or funder that granted it. Every worked sample
    #: found carries it beside the award name -- Toronto prints "Instructor of
    #: the Year" over "Doctor of Pharmacy program, University of Toronto";
    #: Berkeley bolds "Chancellor's Fellowship ..., UC Berkeley". It was the one
    #: field every source agreed on and the one this model could not hold.
    awarding_body: str | None = Field(default=None, max_length=300)
    #: Terms, amount, duration or selectivity, as ONE line of prose rather than
    #: four typed fields. UCC asks for "funding body, terms, duration and
    #: amount" and gives its own example as a sentence -- "IRCSS funded fees and
    #: EUR 12,000 stipend" -- and, where the reader will not know the award,
    #: "one of six recipients selected from 3000 applicants". Toronto allows "a
    #: brief line below the honour or award name"; UPenn, "other awards can be
    #: briefly explained". Typed fields here would invite the model to compose
    #: the sentence instead of copying the one the document printed.
    detail: str | None = Field(default=None, max_length=300)


class ReferenceEntry(BaseModel):
    """One named referee. European academic applications routinely expect them.

    Every field but the name is optional for the usual reason: a CV that
    prints a referee without their address must not acquire one here. The
    email is a third party's, so it is compared by verification like any
    other detail -- a referee nobody confirmed is UNSUPPORTED, which is the
    behaviour wanted for a claim that another person will vouch for you.
    """

    model_config = _CONTENT_CONFIG

    name: str = Field(min_length=1, max_length=200)
    position: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=320, pattern=_EMAIL_PATTERN)
    phone: str | None = Field(default=None, max_length=30)
    #: UCC, verbatim: "For supervisor there is a 'please do not contact'
    #: option." It is a live instruction about a third party, printed on the
    #: document beside their address, and there was nowhere to put it -- so a
    #: CV carrying it lost exactly the part that matters. Defaults False, so
    #: only a document that says so can set it.
    do_not_contact: bool = False


class SkillEntry(BaseModel):
    """One skill, optionally filed under a heading the applicant chose.

    A flat list cannot represent the grouping a real CV uses ("Core
    competencies", "Chemoinformatics and data libraries", "Tools"), and no
    rule in either ruleset mandates or forbids grouping -- S-015 bans skill
    *graphics*, not headings. So the category is optional: content that
    carries none renders exactly as a flat list did.
    """

    model_config = _CONTENT_CONFIG

    name: str = Field(min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    #: How this name was derived: "language" (a host byte count), "library" (a
    #: parsed import or a declared manifest entry) or "technique" (read by a
    #: model out of the project's prose). Tailoring reads this rather than the
    #: rendered heading, which is a presentation choice and can be renamed.
    kind: str | None = Field(default=None, max_length=20)
    #: What backs the name, in a sentence a human can check: "12431 bytes",
    #: "imported by 9 files", or the excerpt that named a technique.
    evidence: str | None = Field(default=None, max_length=1_000)


#: Europass's own labels and order for the CEFR self-assessment grid.
#: The Council of Europe's six levels. S-014 asks for the code "optionally +
#: plain word", and a bare "C1" is the least the CEFR can say.
def _cefr_code(value: object) -> object:
    """Reduce a stated level to its CEFR code, or leave it exactly as stated.

    The field is named for a code and _CEFR_WORDS is keyed on one, but a real
    CV writes "C1 level" and the extractor carries the document's own wording
    through on purpose. That reached the page as "C1 level (C1 level)" -- the
    word lookup missed, level_word fell back to the raw string, and the
    template printed it beside itself.

    Here rather than in the template because self_assessment falls back to
    cefr_level, so the same value was being sent to the live Europass API as a
    CEFR level. A string this cannot recognise is returned untouched: "Native"
    is a claim someone made, not a code to repair.
    """
    if isinstance(value, str) and (match := re.match(r"\s*([ABCabc][12])\b", value)):
        return match.group(1).upper()
    return value


_CEFR_WORDS = {
    "A1": "Beginner",
    "A2": "Elementary",
    "B1": "Intermediate",
    "B2": "Upper intermediate",
    "C1": "Advanced",
    "C2": "Proficient",
}

_SELF_ASSESSMENT_SKILLS: tuple[tuple[str, str], ...] = (
    ("Listening", "listening"),
    ("Reading", "reading"),
    ("Spoken interaction", "spoken_interaction"),
    ("Spoken production", "spoken_production"),
    ("Writing", "writing"),
)


class LanguageEntry(BaseModel):
    model_config = _CONTENT_CONFIG

    language: str = Field(min_length=1, max_length=100)
    cefr_level: Annotated[str | None, BeforeValidator(_cefr_code)] = Field(
        default=None, max_length=10
    )
    test_name: str | None = Field(default=None, max_length=100)
    test_score: str | None = Field(default=None, max_length=50)
    #: Europass self-assessment. None means "not separately assessed" and
    #: falls back to cefr_level at render time; it never means "no skill".
    #: Nothing writes these today -- they are populated by the student, and
    #: the model is told not to infer them (see ingestion/generation).
    listening: str | None = Field(default=None, max_length=10)
    reading: str | None = Field(default=None, max_length=10)
    spoken_interaction: str | None = Field(default=None, max_length=10)
    spoken_production: str | None = Field(default=None, max_length=10)
    writing: str | None = Field(default=None, max_length=10)
    #: Europass sends mother tongues and other languages as different fields.
    #: False means "not stated", which is why it is not Optional -- there is
    #: no third state, and "not stated" and "not their mother tongue" both
    #: correctly render as an entry under otherLanguages.
    mother_tongue: bool = False

    @property
    def level_word(self) -> str:
        """S-014's plain word for cefr_level. A property for the same reason
        self_assessment is one: the template stays a loop."""
        return _CEFR_WORDS.get(self.cefr_level or "", self.cefr_level or "")

    @property
    def self_assessment(self) -> tuple[tuple[str, str | None], ...]:
        """The five Europass sub-skills, each falling back to cefr_level.

        A student who stated one overall level gets that level across the
        grid: it is their own claim, applied uniformly, and it is what they
        would write themselves if handed the form. Labels are carried so the
        template stays a loop and the Europass API mapper knows which column
        is which.
        """
        return tuple(
            (label, getattr(self, field) or self.cefr_level)
            for label, field in _SELF_ASSESSMENT_SKILLS
        )


#: Shared with gaps.answer_questions, which refuses a longer answer at the
#: form. The ledger stores whatever string it is handed, so without that guard
#: a long answer becomes a fact every later generation fails to validate.
TIMELINE_STATEMENT_MAX = 300


class TimelineEntry(_RangeEntry):
    """A span nothing else on the CV covers, and the line that accounts for it.

    Not an ExperienceEntry with the awkward fields left blank: that model
    requires an employer and at least one bullet, and S-045 measured what
    Cambridge's own samples print for a gap -- "Full-time carer for family
    member", "3 months' full-time job-hunting" -- which has neither. Required
    by ETH, TUM ("must not contain any gaps longer than 3 months"), DAAD PRIME
    (R-011), uni-assist (R-020) and Harvard GSD.

    One statement, not bullets. A gap is accounted for, not sold: the bullet
    shape invites a model or a student to build an achievement out of a period
    of unemployment or illness, which is the opposite of what every source
    asks for.
    """

    model_config = _CONTENT_CONFIG

    start_date: CVDate = None
    end_date: CVEndDate = None
    statement: Annotated[str, BeforeValidator(_tidy_prose)] = Field(
        min_length=1, max_length=TIMELINE_STATEMENT_MAX
    )


def open_span_end(start: date, starts: Iterable[date | None]) -> date | None:
    """Where an open-ended gap statement stops: the next entry to start after it.

    A trailing gap is answered with no end date, because the span runs to
    today -- but only until the student adds the post that ended it. Read as
    "to today" forever, that post prints beside "Feb 2024 -- present" and the
    open span hides every gap after it from both detectors. So it closes at
    the start of the next entry (education, experience, or research where
    dated) that has begun, and is None while none has, which every reader
    already takes as "to today". An entry starting in the future closes
    nothing: the statement was about the time up to now. The stored fact is
    never rewritten -- this is read wherever the span is used.
    """
    today = date.today()
    return min((s for s in starts if s is not None and start < s <= today), default=None)


def closed_timeline(content: CVContent) -> tuple[TimelineEntry, ...]:
    """The gap statements, an open-ended one closed at the next entry's start.

    One reading of where a span ends, shared by the printed rows, the gap
    check and the Europass payload, so no two of them can disagree.
    """
    starts = [
        *(entry.start_date for entry in content.education),
        *(entry.start_date for entry in content.experience),
        *(entry.start_date for entry in content.research),
    ]
    return tuple(
        entry.model_copy(update={"end_date": open_span_end(entry.start_date, starts)})
        if entry.end_date is None and entry.start_date is not None
        else entry
        for entry in content.timeline
    )


class CVContent(BaseModel):
    model_config = _CONTENT_CONFIG

    # 3: awards became AwardEntry rather than bare strings, and every date
    # field is bounded (CVDate). Both broke version 2's shape, and leaving the
    # number at 2 made it mean two incompatible things -- a stored v2 draft
    # then failed on an award's TYPE, which reads as a bug rather than as
    # "this row predates the schema". 2 was: links on the contact header,
    # publications as citations, experience as bullets, dated research
    # entries, categorised skills.
    #
    # Literal, not `int`, and the same shape as europass_queue's
    # `schema_version: Literal[1]`: nothing on this schema is version-aware,
    # so the only useful thing it can do is refuse a row it cannot read. It
    # records which shape a stored row is; it does not migrate one to another.
    # A converter for stored v2 rows belongs in a data migration -- there are
    # none today (DocumentDraft.content has no rows and nothing is wired to a
    # view), which is exactly why this bump has to land now rather than after
    # there are.
    schema_version: Literal[3] = 3
    personal_information: PersonalInformation
    education: tuple[EducationEntry, ...] = Field(min_length=1, max_length=20)
    experience: tuple[ExperienceEntry, ...] = Field(max_length=30)
    research: tuple[ResearchEntry, ...] = Field(max_length=10)
    publications: tuple[PublicationEntry, ...] = Field(max_length=50)
    awards: tuple[AwardEntry, ...] = Field(max_length=30)
    skills: tuple[SkillEntry, ...] = Field(max_length=50)
    languages: tuple[LanguageEntry, ...] = Field(max_length=20)
    #: Deliberately last among the record tuples and defaulted to (): every
    #: CV generated before this field existed validates unchanged, and a CV
    #: with no gaps carries none.
    timeline: tuple[TimelineEntry, ...] = Field(default=(), max_length=20)
    #: Defaulted, unlike every field above it: a stored draft written before
    #: referees existed still validates as version 3, which is what keeps
    #: this from being a fourth incompatible shape.
    references: tuple[ReferenceEntry, ...] = Field(default=(), max_length=10)
    summary: str | None = Field(default=None, max_length=1_000)
    document_language: str = Field(min_length=2, max_length=10)

    @property
    def published_publications(self) -> tuple[PublicationEntry, ...]:
        """Published and accepted work. S-011: kept strictly apart from the
        rest, because listing a manuscript under review among published papers
        overstates the record."""
        return tuple(
            entry
            for entry in self.publications
            if not entry.is_presentation
            and entry.status in (PublicationStatus.PUBLISHED, PublicationStatus.IN_PRESS)
        )

    @property
    def pending_publications(self) -> tuple[PublicationEntry, ...]:
        """Everything not yet accepted: under review or in preparation."""
        return tuple(
            entry
            for entry in self.publications
            if not entry.is_presentation
            and entry.status
            in (PublicationStatus.UNDER_REVIEW, PublicationStatus.IN_PREPARATION)
        )

    @property
    def presentations(self) -> tuple[PublicationEntry, ...]:
        """Conference talks and posters, which are their own currency."""
        return tuple(entry for entry in self.publications if entry.is_presentation)
