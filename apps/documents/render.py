from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import NoReturn, Protocol, cast

from django.template.loader import render_to_string
from pydantic import BaseModel, ValidationError
from pypdf import PdfReader
from weasyprint import HTML
from weasyprint.urls import URLFetcher

from apps.funding.models import FundingOpportunity, Program
from apps.ratelimit import rate_limited

from .constraints import (
    ConstraintRule,
    Enforcement,
    PageDirective,
    directives_from_program,
    resolve_rules,
)
from .europass import EuropassUnavailable, assert_europass_provenance, render_europass_pdf
from .hygiene import normalize_text, scrub_pdf_metadata, to_ascii_punctuation
from .models import DocumentDraft
from .schemas import (
    CVContent,
    EducationEntry,
    ExperienceEntry,
    TimelineEntry,
    closed_timeline,
)

_TEMPLATE_BY_VARIANT = {
    "EUROPASS": "documents/cv_europass.html",
    "GERMAN_TABULAR": "documents/cv_german_tabular.html",
    "STANDARD": "documents/cv_standard.html",
}

#: R-029 (docs/research/cv-rules.csv): a German application is expected in the
#: tabellarischer Lebenslauf, a dates-left two-column grid. Nothing mapped a
#: country onto a variant before this, so cv_german_tabular.html and the
#: `tabular` flag every partial branches on were unreachable: a German
#: application rendered in the international layout while German-convention
#: rules resolved against it.
#:
#: Only where the requirement resolves to STANDARD -- an explicit funder
#: format (Europass, a funder's own template, structured fields) is a
#: published instruction and outranks a country convention.
#:
#: Austria shares the convention (S-008 names DACH). Switzerland does not:
#: it is trilingual, and ETH's own requirement is a gapless history, which is
#: about content rather than layout -- it is seeded as a COUNTRY rule instead.
_TABULAR_COUNTRIES = frozenset({"DE", "AT"})

_REQUIREMENT_TO_VARIANT = {
    "europass_required": "EUROPASS_API",
    "europass_preferred": "EUROPASS_API",
    "any": "STANDARD",
    "funder_template": "FUNDER_TEMPLATE",
    "structured_fields_only": "FIELD_MAPPED",
}

#: A release path that can be re-triggered is a way to hammer a public EU
#: service from our IP, which is how access gets withdrawn.
_EUROPASS_RENDER_LIMIT = 10
_EUROPASS_RENDER_WINDOW_SECONDS = 3600


class RenderRateLimited(EuropassUnavailable):
    """Our own per-student limiter fired -- we never reached europa.eu.

    Distinct from EuropassThrottled: that one means europa.eu itself
    answered with a 429. This one means we stopped ourselves, so a caller
    that counts it toward an availability breaker would let one student's
    approval burst park every other tenant's queue over a problem europa.eu
    never had.
    """


@dataclass(frozen=True)
class RenderedArtifact:
    variant: str
    pdf_bytes: bytes | None
    field_mapped: dict[str, object] | None
    page_count: int | None
    byte_size: int


@dataclass(frozen=True)
class ConstraintViolation:
    rule: ConstraintRule
    detail: str


class PreflightBlocked(ValueError):
    pass


class DraftNotApproved(ValueError):
    pass


class UnsupportedRenderVariant(ValueError):
    """No template exists for this variant.

    Never downgrade silently to STANDARD instead -- an artefact must never
    misreport what was actually rendered, and a downgrade here would put a
    plausible-looking PDF in the wrong format past an approval gate with no
    violation and no warning.
    """


class NetworkFetchRefused(Exception):
    """Raised for any resource the rendered HTML asks WeasyPrint to fetch."""


class ContentHygieneFailed(ValueError):
    """The hygiene pass produced content CVContent itself rejects.

    E.g. a name of only zero-width characters (valid input, passes
    PersonalInformation's min_length) normalizes to "". Carries only the
    offending field path -- never the pydantic ValidationError's repr, which
    embeds the (possibly sensitive) input_value.
    """


def _funder_dispatch() -> dict[str, Callable[[CVContent], RenderedArtifact]]:
    """Imported lazily: the funder modules import render.py for RenderedArtifact
    and render_html_to_artifact, so a module-level import here is a cycle."""
    from .funder_templates.rhodes import render_rhodes
    from .funder_templates.sisgp import render_sisgp

    return {"SISGP": render_sisgp, "RHODES": render_rhodes}


def select_render_variant(
    program: Program | None, opportunity: FundingOpportunity | None = None
) -> str:
    """Map a programme's format requirement onto a render variant.

    A funder's requirement wins over the programme's: a Rhodes applicant fills
    the Rhodes template whatever the university would otherwise accept. Blank
    means the funder states nothing, not that it permits anything.

    Falls back to STANDARD rather than raising: an unknown requirement value is
    a data problem, and a KeyError here would take rendering down for every
    student at that programme.
    """
    requirement = getattr(opportunity, "cv_format_requirement", "") or getattr(
        program, "cv_format_requirement", ""
    )
    variant = _REQUIREMENT_TO_VARIANT.get(requirement, "STANDARD")
    if variant == "STANDARD" and getattr(program, "country_code", "") in _TABULAR_COUNTRIES:
        return "GERMAN_TABULAR"
    return variant


def resolve_variant(draft: DocumentDraft) -> str:
    """The variant this draft would actually render as.

    Public because the document worker needs the same answer *before* it
    decides which queue a render goes to (a EUROPASS_API draft must reach the
    pinned Europass worker, never a local render). Two copies of this
    expression is how the worker and the renderer end up disagreeing about
    what a draft is.
    """
    return draft.render_variant or select_render_variant(
        draft.programme, draft.funding_opportunity
    )


def _clean(value: object) -> object:
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def hygienic_content[ModelT: BaseModel](content: ModelT) -> ModelT:
    """Run every string through the release-time text hygiene pass.

    apps/documents/hygiene.py exists for this; without this call it is dead
    code and invisible characters, bidi overrides and mojibake reach the PDF.

    Generic over the model it validates -- `_clean` already walks the dumped
    JSON without caring what it came from, so only the final
    `model_validate` was ever CVContent-specific. Every existing caller
    passes a CVContent and gets a CVContent back; letter_render.py's
    `hygienic_letter_content` builds on this for LetterContent, adding the
    claim-span re-anchoring a bare hygiene pass cannot do on its own.

    Raises ContentHygieneFailed, not a raw pydantic ValidationError, if
    normalisation leaves a field invalid (e.g. a name of only zero-width
    characters passing input validation and then normalizing to ""):
    ValidationError's repr embeds the offending input_value, which is
    student-supplied document text this repo does not log.
    """
    try:
        return type(content).model_validate(_clean(content.model_dump(mode="json")))
    except ValidationError as error:
        fields = ", ".join(".".join(str(part) for part in err["loc"]) for err in error.errors())
        raise ContentHygieneFailed(f"hygiene pass invalidated field(s): {fields}") from None


class _Dated(Protocol):
    start_date: date | None


def _newest_first[T: _Dated](entries: tuple[T, ...]) -> tuple[T, ...]:
    """Reverse-chronological, per S-001. An undated entry sorts last.

    The leading `is not None` in the key is what puts undated entries last
    under reverse=True; date.min never orders anything, it only keeps the key
    comparable. sorted() is stable, so entries sharing a start_date -- and the
    undated ones, whose keys are all equal -- keep the order the applicant
    gave them.
    """
    return tuple(
        sorted(
            entries,
            key=lambda entry: (entry.start_date is not None, entry.start_date or date.min),
            reverse=True,
        )
    )


def _experience_rows(
    content: CVContent, *, oldest_first: bool
) -> tuple[ExperienceEntry | TimelineEntry, ...]:
    """Posts and gap statements in one run, in whatever direction experience is in.

    ETH (S-047, binding where the admissions page states it) asks the CV to
    "leave no time gaps: ALSO LIST periods when you did not attend school,
    study or work", and TUM's tabular CV "must not contain any gaps longer than
    3 months". Both read as requirements on the chronology a reader scans, so a
    gap is listed where it happened rather than in a section at the foot.

    Experience and not education: ETH's own wording groups a gap with "did not
    attend school, study or work", which makes it a period like a post rather
    than a qualification like a degree.

    Computed HERE and not as a property on CVContent, because ordering in this
    codebase happens at one funnel and in two steps: reverse_chronological
    sorts newest-first, then apply_directives may reverse a section to
    chronological on a programme page's instruction. A sort anywhere downstream
    of that would quietly discard the directive. The direction is passed in from
    the directives (`_oldest_first_sections`) because a CV with zero or one post
    has no direction to read back off `experience`.
    """
    combined: tuple[ExperienceEntry | TimelineEntry, ...] = (
        content.experience + closed_timeline(content)
    )
    rows = _newest_first(combined)
    return tuple(reversed(rows)) if oldest_first else rows


def reverse_chronological(content: CVContent) -> CVContent:
    """Order the dated sections newest-first, whatever order the facts arrived in.

    S-001 is universal and nothing else enforced it: not the schema, not
    generation, not any template. Ordering therefore came from whatever order
    the fact rows reached the model, which was arbitrary until
    unsuperseded_facts gained an ORDER BY and is the applicant's own document
    order now -- and a real CV that lists a BSc above a later MSc then renders
    a CV that reads oldest-first.

    Applied once, at the single funnel every variant passes through. A funder
    template that must present a different order re-sorts locally rather than
    opting out here; none does today. Publications are untouched -- the schema
    carries no date for them to sort on.
    """
    return content.model_copy(
        update={
            "education": _newest_first(content.education),
            "experience": _newest_first(content.experience),
            "research": _newest_first(content.research),
        }
    )


def without_duplicated_posts(content: CVContent) -> CVContent:
    """Drop a research entry that is the same work as an experience entry.

    ExperienceEntry gained a supervisor so an academic post could live in one
    place; nothing then stopped the extractor from ALSO emitting it as a
    research entry, and measured on a real CV it did so in two runs of three
    -- the rendered page listed each of four roles twice, under two headings.
    The prompt now says which section owns a post. This is here because the
    prompt is not deterministic and a rendered document should not depend on
    which way one run went.

    Deliberately narrow: both the exact date range AND the institution must
    match. Titles cannot be compared -- the whole point is that the two
    sections name the same work differently ("Master's Thesis" against
    "AZIMUTH: ..."). A thesis at a different institution, or in a different
    period, is a separate claim and survives.
    """
    posts = {
        (entry.employer, entry.start_date, entry.end_date) for entry in content.experience
    }
    return content.model_copy(
        update={
            "research": tuple(
                entry
                for entry in content.research
                if (entry.institution, entry.start_date, entry.end_date) not in posts
            )
        }
    )


def _fold(value: object) -> object:
    if isinstance(value, str):
        return to_ascii_punctuation(value)
    if isinstance(value, dict):
        return {key: _fold(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_fold(item) for item in value]
    return value


def _pdf_artifact(pdf_bytes: bytes, *, variant: str) -> RenderedArtifact:
    scrubbed = scrub_pdf_metadata(pdf_bytes)
    reader = PdfReader(io.BytesIO(scrubbed))
    return RenderedArtifact(
        variant=variant,
        pdf_bytes=scrubbed,
        field_mapped=None,
        page_count=len(reader.pages),
        byte_size=len(scrubbed),
    )


def _no_fetch(url: str) -> NoReturn:
    """Refuse every resource load WeasyPrint attempts.

    No CV template references an external URL, so nothing legitimate is lost
    (fonts are system fonts). The default fetcher would resolve whatever the
    HTML carried -- server-side, from the worker, where 169.254.170.2 hands
    out the Fargate task role's credentials and NAT provides the way out.
    Refusing here holds whatever a later template or caller does, rather than
    resting on every template staying URL-free.

    WeasyPrint wraps this in URLFetchingError and skips the resource with a
    warning (weasyprint/urls.py fetch, images.py), so a template that grows an
    <img> degrades instead of failing the render.
    """
    raise NetworkFetchRefused(f"refused to fetch {url!r} while rendering")


# The ignore below: weasyprint has no stubs (see pyproject's mypy overrides), so
# URLFetcher is Any and disallow_subclassing_any rejects the base class.
class _RefusingFetcher(URLFetcher):  # type: ignore[misc]
    """A URLFetcher whose fetch always refuses. Subclassed, not a bare function.

    WeasyPrint 70 reads ``url_fetcher._fail_on_errors`` on the exception path
    (weasyprint/urls.py::fetch), so a plain callable -- which is what this used
    to be -- raises AttributeError instead of the refusal we intended, and the
    refusal is the SSRF guard. Inheriting gets that attribute with its default
    of False, which is the behaviour we want: a refused resource is a warning
    and the page still renders.

    ``fetch`` rather than ``__call__`` because ``__call__`` delegates to it, and
    it calls ``_no_fetch`` by name so the module attribute stays the seam tests
    patch. Instantiated per render: URLFetcher carries mutable request state.
    """

    def fetch(self, url: str, headers: dict[str, str] | None = None) -> NoReturn:
        _no_fetch(url)


def render_html_to_artifact(html: str, *, variant: str) -> RenderedArtifact:
    """Shared by this module and every funder-template module (Task 12).

    Does NOT run hygienic_content -- callers must normalise their own content
    (see hygienic_content) before building ``html``, or unnormalised text
    (invisible characters, bidi overrides, mojibake) reaches the PDF.
    """
    return _pdf_artifact(
        HTML(string=html, url_fetcher=_RefusingFetcher()).write_pdf(), variant=variant
    )


#: R-027 / archetype D. The spec assigns archetypes C *and* D to STANDARD, so
#: the difference between them is section order, not a separate variant.
#: R-027's "Teaching" position is absent because CVContent has no teaching
#: field. Its Skills-before-Awards swap IS implemented now: skills used to
#: render from cv_base.html after this loop, so no edit to these tuples could
#: move it and an earlier comment here called the swap "not implemented".
#: It is a partial in the tuple like everything else.
#:
#: Referees are NOT in these tuples, and that is the fix rather than an
#: omission. `references` was the last entry here and still printed above
#: Skills and Languages, because both rendered after the loop -- so the
#: promise "referees go last" was false on every CV that had them. Languages
#: cannot join the tuple (cv_europass.html overrides its block, and a block
#: does not survive an include), so references anchors the end of
#: cv_base.html's body instead, after the languages block. Order is decided
#: in one place again: this tuple, then that tail.
#:
#: Awards follow employment on BOTH tracks. _RESEARCH_SECTIONS used to put
#: them before it, on the stated grounds that "the canonical order for a
#: graduate applicant puts it after presentations and before the non-research
#: posts" -- a claim no rule in either catalog makes, and one that left the
#: two tracks contradicting each other with only the taught one matching
#: R-027. Measured on a real CV: four research posts at EPFL, Groningen, ICIQ
#: and Strasbourg rendered below a list of hackathon placements, putting the
#: weakest evidence in the most prominent position on page one.
_TAUGHT_SECTIONS = (
    "documents/_cv_experience.html",
    "documents/_cv_research.html",
    "documents/_cv_publications.html",
    "documents/_cv_presentations.html",
    "documents/_cv_skills.html",
    "documents/_cv_awards.html",
)
_RESEARCH_SECTIONS = (
    "documents/_cv_research.html",
    "documents/_cv_publications.html",
    "documents/_cv_presentations.html",
    "documents/_cv_experience.html",
    "documents/_cv_skills.html",
    "documents/_cv_awards.html",
)


#: Maps an `emphasise`/`order` directive's section target to the movable
#: partial it names. Education, languages and references are deliberately
#: absent: education already leads every variant and the other two close it,
#: so naming them here would let a directive claim a front position that
#: does not exist.
_SECTION_TEMPLATE = {
    "experience": "documents/_cv_experience.html",
    "research": "documents/_cv_research.html",
    "publications": "documents/_cv_publications.html",
    "skills": "documents/_cv_skills.html",
    "awards": "documents/_cv_awards.html",
}


def _section_order(content: CVContent, *, emphasise: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Research-track ordering when the CV has research to lead with.

    This asks a CONTENT question -- does this CV have research to lead with --
    and deliberately does NOT share constraints.resolve_track, which asks a
    CONTEXT question: what kind of programme is being applied to. The two used
    to share this heuristic, and that coupling was the bug: bucketing a
    research post under `experience` rather than `research` silently changed
    the enforced page limit. Now the programme decides what is enforced and
    the content decides what leads.

    They can legitimately disagree. An applicant with a thesis applying to a
    taught programme leads with Research (they have one) and is held to the
    taught page limit (that is the programme they are applying to). Both are
    right. Where the sections would disagree pointlessly -- everything filed
    under `experience` -- the Research template renders nothing anyway, so
    the order of an empty section does not matter.

    `emphasise` moves a named section ahead of its default position, in the
    order given. Education, languages and references are not in the movable
    list: education already leads every variant and the other two close it.
    """
    # Not `content.research` alone. without_duplicated_posts empties that
    # tuple for exactly the applicant whose research IS their experience --
    # four supervised posts, each previously rendered twice -- so keying off
    # emptiness demoted the most research-heavy CVs to the taught order. A
    # supervisor on an experience entry is the same signal by another route.
    base = (
        _RESEARCH_SECTIONS
        if (content.research or any(entry.supervisor for entry in content.experience))
        else _TAUGHT_SECTIONS
    )
    # dict.fromkeys, not a set: order matters, and two directives naming the
    # same section (or one naming it twice) would otherwise render it twice.
    front = list(dict.fromkeys(
        t for name in emphasise if (t := _SECTION_TEMPLATE.get(name)) in base
    ))
    return tuple(front) + tuple(t for t in base if t not in front)


def _render_pdf(
    content: CVContent,
    *,
    variant: str,
    date_of_issue: date | None = None,
    emphasise: tuple[str, ...] = (),
    oldest_first_sections: frozenset[str] = frozenset(),
) -> RenderedArtifact:
    template = _TEMPLATE_BY_VARIANT.get(variant)
    if template is None:
        raise UnsupportedRenderVariant(f"no render template for variant {variant!r}")
    html = render_to_string(
        template,
        {
            "content": content,
            "section_order": _section_order(content, emphasise=emphasise),
            "date_of_issue": date_of_issue,
            # S-008 (docs/research/cv-style-rules.csv): the tabellarischer
            # Lebenslauf is a dates-LEFT two-column grid; partials branch on
            # this instead of duplicating the R-027 section-order logic.
            "tabular": variant == "GERMAN_TABULAR",
            # Not content.experience: _cv_experience.html renders the posts and
            # the gap statements as one chronology (see _experience_rows).
            "experience_rows": _experience_rows(
                content, oldest_first="experience" in oldest_first_sections
            ),
        },
    )
    return render_html_to_artifact(html, variant=variant)


#: The sections an `order` directive can act on: the ones whose entries carry
#: dates. Everything else in the CV is an unordered list.
_DATED_SECTIONS = ("education", "experience", "research")


def _oldest_first_sections(directives: tuple[PageDirective, ...]) -> frozenset[str]:
    """The dated sections a `chronological` `order` directive flips.

    `cv` is the whole-document target: a sentence that orders the CV
    ("A curriculum vitae in reverse chronological order.") names no
    section, so it applies to every dated one at once. The other
    sections carry no dates, so ordering them means nothing.
    """
    sections: set[str] = set()
    for d in directives:
        if d.action != "order" or d.value != "chronological":
            continue
        targets = _DATED_SECTIONS if d.target == "cv" else (d.target,)
        sections.update(t for t in targets if t in _DATED_SECTIONS)
    return frozenset(sections)


def apply_directives(content: CVContent, directives: tuple[PageDirective, ...]) -> CVContent:
    """`order` only: the one directive that changes the content object.

    Runs AFTER reverse_chronological, so `chronological` is the only value
    that changes anything -- it reverses a section the universal rule just
    sorted newest-first; `reverse_chronological` restates that default, so it
    writes nothing back. `include` is generation's (the field renders if
    present) and `emphasise` is _section_order's.
    """
    update: dict[str, object] = {
        section: tuple(reversed(getattr(content, section)))
        for section in _oldest_first_sections(directives)
    }
    return content.model_copy(update=update) if update else content


def _render_field_mapped(content: CVContent) -> RenderedArtifact:
    # Portal form fields mangle non-ASCII punctuation, so fold it here and only
    # here -- the PDF variants keep typographic punctuation.
    dumped = cast(dict[str, object], _fold(content.model_dump(mode="json")))
    payload = json.dumps(dumped, sort_keys=True).encode()
    return RenderedArtifact(
        variant="FIELD_MAPPED",
        pdf_bytes=None,
        field_mapped=dumped,
        page_count=None,
        byte_size=len(payload),
    )


def _check_max_pages(
    rule: ConstraintRule, content: object, artifact: RenderedArtifact
) -> str | None:
    if artifact.page_count is None or artifact.page_count <= int(cast(int, rule.value)):
        return None
    return f"{artifact.page_count} pages exceeds {rule.value}"


def _check_final_page_fill(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """S-022: a near-empty final page reads as careless. S-009: fill it or cut.

    The only floor among these checks -- every other one is a cap, which is
    why this failure survived them all: a CV spilling three lines onto page 2
    passes max_pages and max_bytes and lands on an admissions desk looking
    careless, which is precisely the impression S-022 records reviewers acting
    on.

    Measured from the PDF's own extracted text, not from WeasyPrint's layout
    boxes. Those are a private API and would mean rendering through
    Document.render() instead of write_pdf(); this needs no more precision
    than "is the last page nearly blank", and a CV is text.

    REPORTS, NEVER TRIMS. The other two options in the issue that raised this
    are both refused here: dropping content to fit is the engine editing the
    applicant's document, which the anti-fabrication design forbids, and
    tightening spacing automatically would fight the deterministic render.
    The student is told, and decides.
    """
    page_count = artifact.page_count
    if artifact.pdf_bytes is None or page_count is None or page_count < 2:
        # One page cannot carry a widow, and averaging over no earlier pages
        # would raise rather than report.
        return None
    pages = [
        len((page.extract_text() or "").strip())
        for page in PdfReader(io.BytesIO(artifact.pdf_bytes)).pages
    ]
    average = sum(pages[:-1]) / len(pages[:-1])
    if average == 0:
        # Every earlier page is blank: whatever is wrong here, it is not that
        # the last page is emptier than its neighbours.
        return None
    fill = pages[-1] / average
    if fill >= float(cast(float, rule.value)):
        return None
    return (
        f"final page carries {fill:.0%} of an average page; "
        f"fill it or cut to {page_count - 1}"
    )


def _check_max_bytes(
    rule: ConstraintRule, content: object, artifact: RenderedArtifact
) -> str | None:
    if artifact.byte_size <= int(cast(int, rule.value)):
        return None
    return f"{artifact.byte_size} bytes exceeds {rule.value}"


def _check_photo(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    if rule.value is False and content.personal_information.photo_url:
        return "content includes a photo"
    return None


def _check_date_of_birth(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    if rule.value is False and content.personal_information.date_of_birth is not None:
        return "content includes a date of birth"
    return None


def _check_max_entries(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    for section, limit in dict(cast(dict[str, object], rule.value)).items():
        actual = len(cast(tuple[object, ...], getattr(content, section, ())))
        if actual > int(cast(int, limit)):
            return f"{section} has {actual} entries, limit {limit}"
    return None


def _check_language(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """R-072 (Eiffel) allows French *or* English, so a rule may name a set.
    A bare string keeps its exact previous meaning."""
    allowed = rule.value if isinstance(rule.value, list) else [rule.value]
    if content.document_language in [str(item) for item in allowed]:
        return None
    return f"document language {content.document_language!r} is not {rule.value!r}"


def _check_date_of_issue(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """Verify the date-of-issue line we emit actually reached the artefact.

    Unlike signature_required -- a wet signature we cannot see from here, which
    stays deliberately uncheckable -- this is our own output, so a BINDING rule
    is satisfiable rather than a permanent block. Before this, DAAD EPOS's
    binding date-of-issue rule made the CV unrenderable (R-070).
    """
    if not rule.value:
        return None
    if artifact.pdf_bytes is None:
        return "variant produces no PDF to carry a date of issue"
    pages = PdfReader(io.BytesIO(artifact.pdf_bytes)).pages
    text = "".join(page.extract_text() or "" for page in pages)
    return None if date.today().isoformat() in text else "no date-of-issue line in the artefact"


def _check_required_fields(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """Named PersonalInformation fields must be present and non-empty.

    Serves R-079 (SISGP mandates Sex, Date of birth and Citizenship as fixed
    template fields). Without this checker the rule could not be seeded at all:
    a BINDING rule whose key has no checker fails closed, which would make
    every SISGP CV unrenderable.
    """
    missing = [
        field
        for field in cast(list[str], rule.value)
        if not str(getattr(content.personal_information, field, "") or "").strip()
    ]
    return f"missing required fields: {', '.join(missing)}" if missing else None


def _check_prohibited_content(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """Content classes a funder forbids.

    One token today: "hyperlinks", for R-017 (Fulbright). An unrecognised
    token is reported rather than ignored -- a prohibition we do not
    understand is not a prohibition we have satisfied.
    """
    found: list[str] = []
    for entry in cast(list[str], rule.value):
        if entry != "hyperlinks":
            return f"unrecognised prohibited-content token {entry!r}"
        if content.personal_information.links or any(
            pub.doi for pub in content.publications
        ):
            found.append(entry)
    return f"content includes prohibited {', '.join(found)}" if found else None


def _check_no_unexplained_gaps(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """Report the first stretch of unaccounted time in the history.

    Education and experience together, because either accounts for a period:
    a year spent studying is not a gap in a CV that lists the degree. Spans
    are merged as they are walked, so an internship inside a degree does not
    read as a gap when the degree ends later.

    An open-ended entry runs to today. Research entries are excluded: they
    are optional-dated by design (a thesis DATA gives no dates for must not
    acquire any), so treating an undated one as coverage would silently close
    a real gap.

    Gap statements count where the CV prints them -- the _render_pdf variants,
    whose experience run carries the rows (_experience_rows), and EUROPASS_API,
    whose payload sends them as work experiences (europass._work_rows). The
    funder templates print none, so on those the span is still unexplained and
    is reported.

    Nothing before the first entry is judged. uni-assist asks for a history
    "from your first school" and no CVContent field says when school started,
    so a checker that guessed would report a gap on every CV that omits
    primary education -- which is all of them.
    """
    limit = int(cast(int, rule.value))
    dated: list[EducationEntry | ExperienceEntry | TimelineEntry] = [
        *content.education,
        *content.experience,
    ]
    if artifact.variant in _TEMPLATE_BY_VARIANT or artifact.variant == "EUROPASS_API":
        dated.extend(closed_timeline(content))
    # An entry with no start date accounts for no period, so it can neither
    # open nor close a gap. Every date became optional on 2026-08-31 (one
    # unreadable field was failing the whole document), so this is now an
    # ordinary case rather than an impossible one.
    spans = sorted(
        (entry.start_date, entry.end_date or date.today())
        for entry in dated
        if entry.start_date is not None
    )
    if not spans:
        return None
    covered_to = spans[0][1]
    for start, end in spans[1:]:
        # Days, not a calendar-month difference: the latter counts a gap from
        # 30 June to 1 September of the following year as 15 months when it
        # is 14, and over-reporting on an advisory rule is how an advisory
        # rule gets ignored.
        months = (start - covered_to).days // 30
        if months > limit:
            return (
                f"{months}-month gap between {covered_to.isoformat()} "
                f"and {start.isoformat()}"
            )
        covered_to = max(covered_to, end)
    return None


def _check_ai_use_policy(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """Always reported, never satisfiable -- and that is the design.

    An AI-use policy is a fact about who reads the document, not a defect in
    the artefact: nothing in a rendered PDF shows how it was written. So this
    surfaces the policy to the human approving the draft and stops there.
    Seeded ADVISORY_HIGH_RISK, so render_cv never raises on it; making one
    BINDING would block every CV for that institution, which is the gate the
    letter engine deliberately refused to build.
    """
    return f"funder/institution AI-use policy: {rule.value}"


def _check_surfaced(
    rule: ConstraintRule, content: CVContent, artifact: RenderedArtifact
) -> str | None:
    """Always reported: the rule IS the quote (constraints._MULTI_KEYS).

    Nothing about the artefact satisfies "the readings disagreed" or "no
    field carries this", so the check's only job is to put the page's own
    sentence in front of the person approving the draft.
    """
    return f"the page states: {rule.rule_text}"


_CHECKERS: dict[str, Callable[[ConstraintRule, CVContent, RenderedArtifact], str | None]] = {
    "max_pages": _check_max_pages,
    "max_bytes": _check_max_bytes,
    "min_final_page_fill": _check_final_page_fill,
    "photo_allowed": _check_photo,
    "date_of_birth_allowed": _check_date_of_birth,
    "max_entries_per_section": _check_max_entries,
    "language": _check_language,
    "date_of_issue_required": _check_date_of_issue,
    "required_fields": _check_required_fields,
    "prohibited_content": _check_prohibited_content,
    "no_unexplained_gaps": _check_no_unexplained_gaps,
    "ai_use_policy": _check_ai_use_policy,
    "undecided": _check_surfaced,
    "unapplied": _check_surfaced,
}

#: Checkers decidable from `clean` alone, with no artefact required --
#: date_of_issue_required is included because EUROPASS_API can never satisfy
#: it (there is no way to inject our date line into a Europass-rendered PDF),
#: so it is as decidable pre-render as the others.
_CONTENT_ONLY_KEYS = frozenset(
    {
        "photo_allowed",
        "date_of_birth_allowed",
        "language",
        "max_entries_per_section",
        "date_of_issue_required",
        "required_fields",
        "prohibited_content",
        "no_unexplained_gaps",
    }
)


def _blocked_by_content_only_rules(
    clean: CVContent, constraints: tuple[ConstraintRule, ...], placeholder: RenderedArtifact
) -> bool:
    """True if a BINDING, content-only rule already fails before any render.

    Used only to decide whether the EUROPASS_API branch may make its network
    call -- a PII egress to europa.eu is not worth making for a render that a
    BINDING rule will block regardless. Reuses _CHECKERS rather than
    duplicating checker logic; an unevaluatable rule fails closed (blocks),
    same as the main violation loop below.
    """
    for rule in constraints:
        if rule.enforcement != Enforcement.BINDING or rule.key not in _CONTENT_ONLY_KEYS:
            continue
        checker = _CHECKERS.get(rule.key)
        if checker is None:
            return True
        try:
            detail = checker(rule, clean, placeholder)
        except (TypeError, ValueError, KeyError, AttributeError):
            detail = "could not evaluate rule"
        if detail is not None:
            return True
    return False


#: Universal style rules the catalog does not carry, applied to every render.
#:
#: S-* rules live in docs/research/cv-style-rules.csv and are implemented in
#: CODE, never seeded: all twenty rows in catalog_seed.SEED_RULES are funder
#: (R-*) rules, S-001's ordering is reverse_chronological above and S-008's
#: grid is the `tabular` template flag. Seeding this one instead would make it
#: depend on `manage.py seed_cv_rules` having been run by hand -- and a check
#: that silently never fires is worse than no check, because the pre-flight
#: then reports a clean CV either way.
#:
#: A catalog rule on the same key wins over this: resolve_rules has already
#: merged by scope, so anything reaching here for this key is more specific
#: than universal by construction.
_UNIVERSAL_RULES = (
    ConstraintRule(
        rule_id="S-022",
        key="min_final_page_fill",
        # A fifth of an average page. The case this was reported from carried
        # only a Languages section on page 2, about 15% -- so the threshold
        # catches it while leaving a genuinely short-but-used last page alone.
        value=0.2,
        enforcement=Enforcement.ADVISORY_STYLE,
        rule_text=(
            "Reviewers cull on carelessness: typos, mixed styles, inconsistent "
            "alignment, cramped leading, widowed pages (a near-empty final page "
            "reads as careless)"
        ),
        source_url=(
            "https://www.gograd.org/resources/"
            "building-graduate-school-resume-curriculum-vitae/"
        ),
        scope="UNIVERSAL",
    ),
)


def _with_universal_rules(
    constraints: tuple[ConstraintRule, ...],
) -> tuple[ConstraintRule, ...]:
    """Append the universal style rules nothing more specific has overridden."""
    overridden = {rule.key for rule in constraints}
    return (
        *constraints,
        *(rule for rule in _UNIVERSAL_RULES if rule.key not in overridden),
    )


def europass_content(
    content: CVContent, directives: tuple[PageDirective, ...]
) -> tuple[CVContent, bool]:
    """What EUROPASS_API sends: the funnel's content, and whether its experience
    runs oldest first. One function because two places need the same answer --
    the render, and the cache key (europass_render.payload_hash), which must
    hash what is sent or two programmes asking different orders share a PDF.
    """
    clean = apply_directives(
        reverse_chronological(without_duplicated_posts(hygienic_content(content))), directives
    )
    return clean, "experience" in _oldest_first_sections(directives)


def render_cv_with_warnings(
    content: CVContent,
    *,
    variant: str,
    constraints: tuple[ConstraintRule, ...] = (),
    funder_template_id: str | None = None,
    allow_network: bool = False,
    directives: tuple[PageDirective, ...] = (),
) -> tuple[RenderedArtifact, tuple[ConstraintViolation, ...]]:
    # The same funnel the Europass cache key hashes (europass_content), so the
    # key always describes what this render sends.
    clean, _ = europass_content(content, directives)
    emphasise = tuple(d.target for d in directives if d.action == "emphasise")
    oldest_first = _oldest_first_sections(directives)
    if variant == "EUROPASS_API":
        if allow_network:
            placeholder = RenderedArtifact(
                variant="EUROPASS_API",
                pdf_bytes=None,
                field_mapped=None,
                page_count=None,
                byte_size=0,
            )
            if _blocked_by_content_only_rules(clean, constraints, placeholder):
                # A BINDING rule decidable from the content alone already
                # blocks this render -- do not send the student's PII to
                # europa.eu (name, email, education, employment history) only
                # to raise PreflightBlocked afterwards.
                artifact = placeholder
            else:
                artifact = _pdf_artifact(
                    render_europass_pdf(clean, oldest_first="experience" in oldest_first),
                    variant="EUROPASS_API",
                )
                # Verify the bytes we are actually going to ship, after
                # scrubbing: a hygiene pass that stripped the attachment
                # would otherwise release a CV whose provenance we only
                # checked before scrubbing.
                assert_europass_provenance(cast(bytes, artifact.pdf_bytes))
        else:
            # Preview: no network budget, and no consent yet to send a
            # student's data to a third party. Show the local look-alike,
            # labelled as the look-alike it is.
            artifact = _render_pdf(
                clean,
                variant="EUROPASS",
                emphasise=emphasise,
                oldest_first_sections=oldest_first,
            )
    elif variant == "FUNDER_TEMPLATE":
        dispatch = _funder_dispatch()
        if funder_template_id not in dispatch:
            # Missing or unknown funder_template_id -- there genuinely is no
            # template for it, the same failure mode UnsupportedRenderVariant
            # exists for (it subclasses ValueError, so this is also a caller
            # bug in the ValueError sense the funder-template tests pin).
            raise UnsupportedRenderVariant(
                f"no funder template for funder_template_id {funder_template_id!r}"
            )
        artifact = dispatch[funder_template_id](clean)
    elif variant == "FIELD_MAPPED":
        artifact = _render_field_mapped(clean)
    else:
        # A date-of-issue line is something we EMIT, not something we verify
        # about the world, so the constraint drives rendering rather than only
        # judging it after the fact (R-070).
        wants_date = any(
            rule.key == "date_of_issue_required" and rule.value for rule in constraints
        )
        artifact = _render_pdf(
            clean,
            variant=variant,
            date_of_issue=date.today() if wants_date else None,
            emphasise=emphasise,
            oldest_first_sections=oldest_first,
        )
    violations: list[ConstraintViolation] = []
    for rule in _with_universal_rules(constraints):
        checker = _CHECKERS.get(rule.key)
        if checker is None:
            if rule.enforcement != Enforcement.ADVISORY_STYLE:
                # We cannot verify it, so we will not pretend the artefact
                # satisfies it -- reported as a *violation*, not a raise: this
                # function's whole job is to return violations (Task 13's
                # override flow reads them), and render_cv below still turns
                # any BINDING one into a PreflightBlocked, so fail-closed
                # behaviour is unchanged.
                #
                # ADVISORY_HIGH_RISK is reported here too, and that is the
                # whole point of the tier. R-031 (Germany: signature on the
                # last page) is the live case: it was downgraded from BINDING
                # so it would not block every German CV, and it has no checker
                # by design -- a wet signature is not visible from here.
                # Staying silent would make the downgrade meaningless, turning
                # "blocks everything" into "does nothing" with nothing in
                # between. ADVISORY_STYLE stays silent: unverifiable style
                # advice is noise, not risk.
                violations.append(
                    ConstraintViolation(rule, f"no pre-flight check for {rule.key!r}")
                )
            continue
        try:
            detail = checker(rule, clean, artifact)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            # Malformed rule.value (wrong type/shape) is the same "we cannot
            # verify it" case as an unrecognised key above -- fail closed as
            # a violation instead of crashing this function for every other
            # rule in the same list.
            detail = f"could not evaluate rule: {exc}"
        if detail is not None:
            violations.append(ConstraintViolation(rule, detail))
    return artifact, tuple(violations)


def render_cv(
    content: CVContent,
    *,
    variant: str,
    constraints: tuple[ConstraintRule, ...] = (),
    funder_template_id: str | None = None,
    allow_network: bool = False,
    directives: tuple[PageDirective, ...] = (),
) -> RenderedArtifact:
    """Preview render. Nothing produced here is persisted -- see render_draft."""
    artifact, violations = render_cv_with_warnings(
        content,
        variant=variant,
        constraints=constraints,
        funder_template_id=funder_template_id,
        allow_network=allow_network,
        directives=directives,
    )
    binding = [v for v in violations if v.rule.enforcement == Enforcement.BINDING]
    if binding:
        raise PreflightBlocked("; ".join(f"{v.rule.rule_id}: {v.detail}" for v in binding))
    return artifact


def render_draft(
    *,
    draft: DocumentDraft,
    constraints: tuple[ConstraintRule, ...] = (),
    funder_template_id: str | None = None,
) -> RenderedArtifact:
    """Release render. Only an APPROVED draft becomes an artefact anyone keeps."""
    if draft.status != DocumentDraft.Status.APPROVED:
        raise DraftNotApproved(f"draft is {draft.status}, not APPROVED")
    content = CVContent.model_validate(draft.content)
    if not constraints:
        constraints = resolve_rules(
            draft.programme, draft.funding_opportunity, content=content
        )
    variant = resolve_variant(draft)
    # Per-STUDENT abuse guard only -- "one student cannot trigger a hundred
    # renders", keyed by draft.student_id on Django's cache (shared Redis/Valkey
    # in production, apps/ratelimit.py). The GLOBAL rate control is not here --
    # it is the worker's drain rate (apps/documents/europass_worker.py).
    # Guard on the RESOLVED variant, not draft.render_variant: a blank
    # render_variant can now resolve to EUROPASS_API from the programme or
    # funder, and a guard reading the raw field would let every such draft
    # reach the public EU API with no limit at all.
    if variant == "EUROPASS_API" and rate_limited(
        "europass-render",
        draft.student_id,
        limit=_EUROPASS_RENDER_LIMIT,
        window_seconds=_EUROPASS_RENDER_WINDOW_SECONDS,
    ):
        raise RenderRateLimited("Europass render rate limit reached; retry later")
    return render_cv(
        content,
        variant=variant,
        constraints=constraints,
        funder_template_id=funder_template_id,
        allow_network=True,
        directives=directives_from_program(draft.programme)
        if draft.programme is not None
        else (),
    )
