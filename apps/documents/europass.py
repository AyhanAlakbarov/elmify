"""Render a CV by having europa.eu render it.

The local EUROPASS template is a look-alike: correct sections, no Europass
provenance. What a funder can actually check is the ``attachment.xml`` every
Europass PDF embeds, and ours embeds nothing. This module gets the real thing.

There is no fallback. Every failure here raises, and a caller that wanted a
Europass CV does not silently receive something else -- see the plan's "The
one thing this plan changes from the spec".
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from io import BytesIO
from time import sleep
from typing import Protocol, cast
from urllib.parse import quote

import urllib3
from pypdf import PdfReader

from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    PublicationEntry,
    ResearchEntry,
    TimelineEntry,
    closed_timeline,
)
from apps.research.egress import (
    MAX_RESPONSE_BYTES,
    ResolvedTarget,
    Response,
    UnsafeTarget,
    validate_public_url,
)

#: Pinned in code, not in settings. There is no legitimate reason to point
#: this at another origin, so there is no way to.
EUROPASS_ORIGIN = "https://europa.eu"
_API_ROOT = "/europass/eportfolio/api"
_MAX_BYTES = MAX_RESPONSE_BYTES
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)
_TIMEOUT = urllib3.Timeout(connect=5, read=30)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

#: What the renderer prints, in print order. NOT decoration: europa.eu
#: renders *only* the sections named here, so an empty list -- which is what
#: this sent until the blank-CV investigation -- yields a one-page PDF with
#: nothing but the name and email on it, whatever the profile contains.
#: The keys are kebab-case section ids read out of the editor's own bundle
#: (the enum whose members are PERSONAL_INFORMATION="personal-information",
#: EDUCATION_TRAINING="education-training", ... ); camelCase guesses are
#: stored verbatim by the API and then silently ignored by the renderer, so
#: a wrong key here fails exactly like an empty list. Sections with no
#: entries are dropped by the renderer itself, so listing all of them is
#: safe and keeps the order stable across students.
_PRINTED_SECTIONS = (
    "personal-information",
    "work-experience",
    "education-training",
    "language",
    "profile-skills",
    "projects",
    "publication",
    "honour-award",
    "certifications",
)

#: The PDF is rendered asynchronously: the first download after a render
#: routinely answers 204 with no body, and 200 with the PDF a moment later.
#: Treating that 204 as a failure loses a perfectly good render.
_DOWNLOAD_ATTEMPTS = 6
_DOWNLOAD_POLL_SECONDS = 2


class EuropassUnavailable(RuntimeError):
    """europa.eu did not produce a CV we can use.

    Always transient from the caller's point of view: nothing has been
    written, the draft is untouched, and retrying later is the correct
    response. It is never a reason to render something else instead.
    """


class EuropassNotReady(EuropassUnavailable):
    """The document office has not finished rendering yet (HTTP 204)."""


class EuropassProvenanceMissing(EuropassUnavailable):
    """A PDF came back, but it is not a Europass document."""


#: Used when europa.eu throttles us without saying for how long. Two minutes
#: is long enough to matter and short enough that a spurious 429 does not
#: park the queue for an hour.
_DEFAULT_RETRY_AFTER_SECONDS = 120


class EuropassThrottled(EuropassUnavailable):
    """europa.eu asked us to slow down.

    Distinguished from a generic failure because the response is different:
    a failure is retried, a throttle pauses every caller. Subclasses
    EuropassUnavailable so callers written against the module's documented
    contract keep working unchanged.
    """

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class Transport(Protocol):
    def __call__(
        self,
        target: ResolvedTarget,
        *,
        method: str,
        path: str,
        body_bytes: bytes | None,
        headers_out: dict[str, str],
    ) -> Response: ...


def _request(
    target: ResolvedTarget,
    *,
    method: str,
    path: str,
    body_bytes: bytes | None,
    headers_out: dict[str, str],
) -> Response:
    """Connect to a *validated address*, not to a name.

    Re-resolving the hostname here would reopen the DNS-rebinding window
    validate_public_url just closed, which matters because this runs in the
    worker where 169.254.170.2 hands out the task role's credentials.
    """
    pool = urllib3.HTTPSConnectionPool(
        target.addresses[0],
        target.port,
        assert_hostname=target.host,
        server_hostname=target.host,
        maxsize=1,
    )
    return cast(
        Response,
        pool.urlopen(
            method,
            path,
            body=body_bytes,
            headers=headers_out,
            redirect=False,
            preload_content=False,
            timeout=_TIMEOUT,
            retries=False,
        ),
    )


def _header(headers: object, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    return value if isinstance(value, str) else None


def _set_cookies(headers: object) -> Iterable[str]:
    getlist = getattr(headers, "getlist", None)
    return getlist("Set-Cookie") if getlist is not None else ()


def _retry_after_seconds(headers: object) -> int:
    """Only the delta-seconds form is honoured.

    RFC 7231 also permits an HTTP-date, but parsing one buys a timezone bug
    for a value we would clamp anyway -- the default is a safe read of any
    header we do not understand.
    """
    raw = _header(headers, "Retry-After")
    if raw is None or not raw.strip().isdigit():
        return _DEFAULT_RETRY_AFTER_SECONDS
    return min(int(raw.strip()), 3600)


def _call(
    jar: dict[str, str],
    method: str,
    path: str,
    *,
    body: dict[str, object] | None = None,
    accept: str = "application/json",
    transport: Transport = _request,
) -> bytes:
    """One call to the pinned origin. Validates, sends, absorbs cookies, reads.

    ``jar`` is mutated with any Set-Cookie the response carries -- the API
    issues an XSRF-TOKEN cookie whose value must be echoed as a header on
    every mutating call, so the jar is the session.
    """
    try:
        target = validate_public_url(f"{EUROPASS_ORIGIN}{path}")
        if target.scheme != "https":
            raise EuropassUnavailable("refusing a non-HTTPS Europass endpoint")
        body_bytes = json.dumps(body).encode() if body is not None else None
        headers_out = {
            "Host": target.host,
            "User-Agent": _USER_AGENT,
            "Accept": accept,
        }
        if jar:
            headers_out["Cookie"] = "; ".join(f"{name}={value}" for name, value in jar.items())
        if body_bytes is not None:
            headers_out["Content-Type"] = "application/json"
        token = jar.get("XSRF-TOKEN")
        if token:
            headers_out["X-XSRF-TOKEN"] = token
        response = transport(
            target, method=method, path=path, body_bytes=body_bytes, headers_out=headers_out
        )
    except (OSError, urllib3.exceptions.HTTPError, UnsafeTarget) as error:
        raise EuropassUnavailable(f"europa.eu was unreachable for {method} {path}") from error
    try:
        for raw in _set_cookies(response.headers):
            name, _, rest = raw.partition("=")
            if name.strip():
                jar[name.strip()] = rest.split(";", 1)[0].strip()
        if response.status in _REDIRECT_STATUSES:
            # Four known endpoints. A redirect means the API moved, and
            # chasing it would send a student's data somewhere unvalidated.
            raise EuropassUnavailable(f"europa.eu redirected {method} {path}")
        if response.status == 429:
            raise EuropassThrottled(
                "europa.eu throttled the request",
                retry_after_seconds=_retry_after_seconds(response.headers),
            )
        if response.status >= 400:
            raise EuropassUnavailable(f"europa.eu returned HTTP {response.status}")
        if response.status == 204:
            raise EuropassNotReady(f"europa.eu has no content yet for {method} {path}")
        content_type = (_header(response.headers, "Content-Type") or "").split(";", 1)[0]
        if content_type != accept:
            raise EuropassUnavailable(f"expected {accept}, got {content_type or 'nothing'}")
        chunks: list[bytes] = []
        size = 0
        while chunk := response.read(64 * 1024, decode_content=True):
            size += len(chunk)
            if size > _MAX_BYTES:
                raise EuropassUnavailable(f"response exceeded {_MAX_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
    except (OSError, urllib3.exceptions.HTTPError) as error:
        # preload_content=False means this loop is where most of the wire
        # time is spent -- a mid-body read timeout is the most likely
        # production failure, and it must not escape as a raw urllib3 error.
        raise EuropassUnavailable(f"europa.eu connection failed reading {method} {path}") from error
    finally:
        response.release_conn()


#: ponytail: the languages this product actually sees, not all of ISO 639-3.
#: An unmapped language raises rather than silently dropping out of the CV;
#: the fix is one entry. Upgrade path is a real ISO 639 table if the catalogue
#: ever outgrows a dict.
_LANGUAGE_CODES = {
    "azerbaijani": "aze",
    "english": "eng",
    "russian": "rus",
    "turkish": "tur",
    "german": "deu",
    "french": "fra",
    "spanish": "spa",
    "italian": "ita",
    "portuguese": "por",
    "dutch": "nld",
    "polish": "pol",
    "czech": "ces",
    "swedish": "swe",
    "norwegian": "nor",
    "danish": "dan",
    "finnish": "fin",
    "greek": "ell",
    "hungarian": "hun",
    "romanian": "ron",
    "arabic": "ara",
    "persian": "fas",
    "farsi": "fas",
    "georgian": "kat",
    "ukrainian": "ukr",
    "chinese": "zho",
    "japanese": "jpn",
    "korean": "kor",
    "hindi": "hin",
    "urdu": "urd",
    "hebrew": "heb",
}

#: Europass's own key for each of the five CEFR sub-skills, in the order
#: LanguageEntry.self_assessment returns them.
_SUB_SKILL_KEYS = (
    "listening",
    "reading",
    "spokenInteraction",
    "spokenProduction",
    "writing",
)


def _language_code(name: str) -> str:
    try:
        return _LANGUAGE_CODES[name.strip().casefold()]
    except KeyError:
        # Do not echo the student-supplied language text into an exception
        # message -- ContentHygieneFailed's docstring states the convention.
        raise EuropassUnavailable(
            "no Europass language code for a declared language; add it to _LANGUAGE_CODES"
        ) from None


def _name_parts(full_name: str) -> tuple[str, str]:
    """Europass wants two boxes; CVContent carries one verified name.

    ponytail: the last whitespace token is the family name. Wrong for Spanish
    double surnames and patronymic-final orders, and knowingly so -- the
    upgrade path is optional given_name/family_name on PersonalInformation,
    sourced from the IDENTITY fact and used when present, which needs no
    migration because CVContent is a pydantic schema.

    Splitting at all is the one inference this design permits, for the same
    reason generate_cv refuses to stamp full_name: a name can be wrong in a
    way only a human catches, and the student sees this at the approval gate.
    """
    parts = full_name.split()
    if len(parts) < 2:
        return full_name, ""
    return " ".join(parts[:-1]), parts[-1]


def _date_obj(value: date | None) -> dict[str, object] | None:
    """Europass dates are nested objects everywhere they appear, not ISO
    strings -- one helper so every call site agrees on the shape. A null
    date is `null`, not an empty nested object."""
    if value is None:
        return None
    return {"date": value.isoformat(), "dateType": "DAY", "empty": False}


def _language_entry(entry: LanguageEntry) -> dict[str, object]:
    """Native and other-language entries need required sibling fields --
    a bare {"language": ...} is what caused six HTTP 500s before the real
    shape was captured (see task-4b-report.md).

    ponytail (M-2): a sub-skill key is omitted entirely when its level is
    None, never sent as null -- captured entries always carry strings for
    a stated sub-skill, and native entries omit the five keys entirely, so
    omission is the only value shape ever observed. A language with no
    cefr_level and no per-skill override ends up with no CEFR keys at all,
    same as a native entry.
    """
    payload: dict[str, object] = {
        "languageCategory": "NORMAL",
        "language": _language_code(entry.language),
    }
    if not entry.mother_tongue:
        levels = (level for _label, level in entry.self_assessment)
        payload.update(
            {key: level for key, level in zip(_SUB_SKILL_KEYS, levels) if level is not None}
        )
    payload["mediaAttachments"] = []
    return payload


def _education_entry(order: int, entry: EducationEntry) -> dict[str, object]:
    """Fields we have no verified data or shape for are left null, per the
    task-5 brief's explicit correction table -- including finalGrade and
    numberOfCredits, even though EducationEntry carries grade_native/
    grade_scale/grade_conversion/ects_credits. That data stays unmapped
    until a follow-up task confirms the live shape for those fields."""
    return {
        "order": order,
        "qualification": entry.degree_english or entry.degree_as_awarded,
        "organisationName": entry.institution_english or entry.institution_original,
        "streetAddress": None,
        "postalCode": None,
        "city": entry.city,
        # None where the document named no country: the field became optional
        # on 2026-08-31 (a required one made the model invent 'NY' and 'UQ'),
        # and Europass is sent the absence rather than a guess.
        "country": entry.country.lower() if entry.country else None,
        "website": None,
        "creationDate": None,
        "startDate": _date_obj(entry.start_date),
        "endDate": _date_obj(entry.end_date),
        "ongoing": entry.end_date is None,
        "description": None,
        "studyFields": [],
        "finalGrade": None,
        "thesis": None,
        "eqf": None,
        "nationalClassification": None,
        "typeOfCredits": None,
        "numberOfCredits": None,
        "validUntil": None,
        "mediaAttachments": None,
        "links": [],
    }


def _work_rows(content: CVContent, *, oldest_first: bool) -> list[dict[str, object]]:
    """Posts and gap statements as one run of Europass work experiences.

    Owner decision 2026-10-06: europa.eu prints the same history the CV does,
    so a gap row goes into the one shape this API is observed to accept for a
    dated period -- the captured work-experience entry -- with the statement as
    the occupation and no employer, the way the CV prints it.

    A CV without gap rows sends its posts exactly as the funnel ordered them.
    With gap rows the merged run follows the same direction: newest first by
    default, oldest first when the programme's `order` directive reversed the
    experience section (render._oldest_first_sections passes it in) -- the
    posts arrive already ordered, so only the merge needs telling.
    """
    gaps = closed_timeline(content)
    if not gaps:
        return [
            _work_experience_entry(order, entry) for order, entry in enumerate(content.experience)
        ]
    merged: list[ExperienceEntry | TimelineEntry] = [*content.experience, *gaps]
    merged.sort(key=lambda entry: entry.start_date or date.min, reverse=not oldest_first)
    return [
        _gap_entry(order, entry)
        if isinstance(entry, TimelineEntry)
        else _work_experience_entry(order, entry)
        for order, entry in enumerate(merged)
    ]


def _gap_entry(order: int, entry: TimelineEntry) -> dict[str, object]:
    """A gap statement in the captured work-experience shape. Every absent
    part is "", never None -- see _work_experience_entry on why."""
    return {
        "order": order,
        "employerDetails": {
            "employer": "",
            "organisationDepartment": None,
            "organisationBusinessSector": None,
            "organisationWebsite": None,
            "organisationContactEmail": None,
            "organisationAddress": {
                "addressPart1": "",
                "addressPart2": "",
                "postalCode": "",
                "city": "",
                "country": "",
            },
        },
        "workExperience": {
            "occupation": {"label": entry.statement, "uri": None},
            "creationDate": None,
            "startDate": _date_obj(entry.start_date),
            "endDate": _date_obj(entry.end_date),
            "ongoing": entry.end_date is None,
            "mainActivities": "",
            "mediaAttachments": None,
            "links": None,
            "groupReference": None,
        },
    }


def _work_experience_entry(order: int, entry: ExperienceEntry) -> dict[str, object]:
    """Nested, not flat: employerDetails carries the org, workExperience
    carries the occupation. entry.unpaid is not routed to a separate
    section here -- every other CV variant ignores that field too, and the
    task brief's flat mapping made no exception for it."""
    # Empty string, never None: the three sibling keys in organisationAddress
    # below already send "" for an absent part, and that shape is observed to
    # work. A null in either of these is a shape nobody has seen this API
    # accept -- the captured fixture has city and country populated in its one
    # address block -- and _language_entry's docstring records what guessing at
    # this API's shape costs (six HTTP 500s). Nothing local would catch it:
    # no test talks to europa.eu, europass_canary is deliberately not a test,
    # and this module has no fallback, so a rejected payload fails the CV
    # outright rather than degrading.
    country = entry.country.lower() if entry.country else ""
    return {
        "order": order,
        "employerDetails": {
            "employer": entry.employer,
            "organisationDepartment": None,
            "organisationBusinessSector": None,
            "organisationWebsite": None,
            "organisationContactEmail": None,
            "organisationAddress": {
                "addressPart1": "",
                "addressPart2": "",
                "postalCode": "",
                "city": entry.city or "",
                "country": country,
            },
        },
        "workExperience": {
            "occupation": {"label": entry.title, "uri": None},
            "creationDate": None,
            "startDate": _date_obj(entry.start_date),
            "endDate": _date_obj(entry.end_date),
            "ongoing": entry.end_date is None,
            # Europass has one free-text field here, so the bullets join with
            # newlines rather than being flattened into a paragraph.
            "mainActivities": "\n".join(entry.bullets),
            "mediaAttachments": None,
            "links": None,
            "groupReference": None,
        },
    }


def _project_entry(order: int, entry: ResearchEntry) -> dict[str, object]:
    """Spec decision: a thesis is a research project. Projects is
    first-class in Candidate.xsd and survives into the embedded XML; a
    custom section titled "Research" would not."""
    description = " ".join(
        part for part in (entry.supervisor, entry.methods, entry.outcomes) if part
    )
    return {
        "order": order,
        "title": entry.thesis_title,
        "description": description or None,
        "creationDate": None,
        "startDate": _date_obj(entry.start_date),
        "endDate": _date_obj(entry.end_date),
        # Only claimable once a start date exists: without one, "ongoing" would
        # be an assertion about a project whose dates the CV never stated.
        "ongoing": entry.start_date is not None and entry.end_date is None,
        "mediaAttachments": None,
        "links": None,
    }


def _publication_entry(order: int, entry: PublicationEntry) -> dict[str, object]:
    """Europass has always had authors/year/doi/journalConference fields; they
    were sent as None only because CVContent held publications as strings."""
    return {
        "order": order,
        "title": entry.title,
        "creationDate": None,
        "year": str(entry.year) if entry.year else None,
        "reference": None,
        "doi": entry.doi,
        # Europass has no status field, so unaccepted work would otherwise
        # arrive indistinguishable from published work (S-011).
        "description": entry.status_label or None,
        "mediaAttachments": None,
        "links": None,
        "authors": ", ".join(entry.authors),
        "journalConference": entry.venue,
        "publisher": None,
        "volumeIssuePages": None,
    }


def _award_entry(order: int, title: str) -> dict[str, object]:
    return {
        "order": order,
        "title": title,
        "description": None,
        "institution": None,
        "creationDate": None,
        "date": None,
        "mediaAttachments": None,
        "links": None,
    }


def europass_payload(content: CVContent, *, oldest_first: bool = False) -> dict[str, object]:
    """CVContent -> the eportfolio profile document. Pure; no network.

    Keeping this pure is the testing strategy: the part that churns when an
    undocumented API shifts is a dictionary, and a dictionary is asserted
    against a captured fixture with no network in CI.

    Key names and value shapes here come from a live capture of the
    Europass editor's own requests (task-4b-report.md), not from the
    original task-5 brief's pre-data guesses -- see that report for the
    per-section field tables this function follows.
    """
    first_name, last_name = _name_parts(content.personal_information.full_name)
    personal = content.personal_information
    languages = content.languages
    return {
        "profile": {
            "language": content.document_language,
            "personalInformation": {
                "firstName": first_name,
                "lastName": last_name,
                "personalMottoLine": None,
                "personalDescription": content.summary,
                # ponytail: sex deliberately dropped (R-12), not mapped from
                # personal.sex. Free text on our side, codification-driven on
                # europa.eu's; the only value ever observed captured was the
                # empty string. Same risk class as phone/dateOfBirth above --
                # a wrong guess 500s the whole render. Upgrade path: capture
                # a populated sex entry, then map it through the real codes.
                "sex": "",
                "nationalities": [],
                "homeCountryCode": None,
                "birthplace": None,
                # ponytail: dateOfBirth deliberately dropped, not mapped from
                # personal.date_of_birth. The captured editor session never
                # populated a birth date, so this field's shape is as
                # unverified as phones (below) -- the same class of guess
                # that produced six HTTP 500s before real data existed.
                # Upgrade path: capture a populated dateOfBirth entry, then
                # map it, the same way education/work dates were captured.
                "dateOfBirth": None,
                "socialMediaWebsites": [],
                "emails": [personal.email],
                # ponytail: phone deliberately dropped (R-9). The captured
                # editor session never populated one, so the entry shape is
                # unverified, and an unverified shape is what produced the
                # earlier 500s. A wrong guess here costs the student their
                # whole CV; a missing phone costs them a phone number.
                # Upgrade path: capture a populated phones entry, then map it.
                "phones": [],
                "addresses": [],
                "websites": [],
                "instantMessengers": [],
                "legalDocuments": [],
                "workPermits": [],
            },
            "workExperiences": {
                "solidWorkExperiences": _work_rows(content, oldest_first=oldest_first),
                "groupedWorkExperiences": [],
            },
            "educationTrainings": [
                _education_entry(order, entry) for order, entry in enumerate(content.education)
            ],
            "languageSkills": {
                "id": None,
                "nativeLanguages": [
                    _language_entry(entry) for entry in languages if entry.mother_tongue
                ],
                "otherLanguages": [
                    _language_entry(entry) for entry in languages if not entry.mother_tongue
                ],
                "showGuidanceLevelSentence": None,
            },
            "projects": [
                _project_entry(order, entry) for order, entry in enumerate(content.research)
            ],
            "publications": [
                _publication_entry(order, entry)
                for order, entry in enumerate(content.publications)
            ],
            "honoursAwards": [
                _award_entry(order, item.title) for order, item in enumerate(content.awards)
            ],
            "profileSkills": {
                "other": [
                    {"type": "digitalSkill", "label": skill.name} for skill in content.skills
                ],
                "groups": [],
                "mediaAttachments": [],
            },
            "preference": {
                "dateFormat": "dd/MM/yyyy",
                "profileStructure": list(_PRINTED_SECTIONS),
            },
            "skillsAssessment": {"assessment": None, "mediaAttachments": []},
            "customSections": [],
        },
        "template": {
            "templateName": "cv-formal",
            "displayLogo": "first",
            "displayPageNumber": False,
            "closingStatement": None,
            "color": "none",
            "fontSize": "medium",
        },
        "profilePicture": None,
    }


def _download_token(body: bytes) -> str:
    try:
        parsed = json.loads(body)
    except ValueError as error:
        # ValueError, not json.JSONDecodeError: non-UTF-8 bytes (e.g. a
        # truncated or gzipped error page) raise UnicodeDecodeError here,
        # which is a ValueError but not a JSONDecodeError.
        raise EuropassUnavailable("render returned a non-JSON body") from error
    if isinstance(parsed, str) and parsed:
        return parsed
    if isinstance(parsed, dict):
        value = parsed.get("id")
        if isinstance(value, str) and value:
            return value
    raise EuropassUnavailable("render returned no download token")


def render_europass_pdf(
    content: CVContent, *, oldest_first: bool = False, transport: Transport = _request
) -> bytes:
    """The four calls. Raises EuropassUnavailable; never returns a substitute."""
    payload = europass_payload(content, oldest_first=oldest_first)
    jar: dict[str, str] = {}
    _call(jar, "GET", f"{_API_ROOT}/frontend-config", transport=transport)
    create_body = _call(jar, "POST", f"{_API_ROOT}/eprofile/cv", body=payload, transport=transport)
    try:
        created = json.loads(create_body)
    except ValueError as error:
        # ValueError, not json.JSONDecodeError: see _download_token's note.
        raise EuropassUnavailable("create returned a non-JSON body") from error
    cv_id = created.get("id") if isinstance(created, dict) else None
    if not isinstance(cv_id, str) or not cv_id:
        raise EuropassUnavailable("create returned no CV id")
    # Create seeds an *empty* CV: it keeps personalInformation's name/email
    # and the template block, and silently drops every content section with
    # "errors": {} -- tests/documents/fixtures/europass_profile.json is a
    # readback taken right after create and shows exactly that. PUT is the
    # write path that persists sections (round-trip verified in
    # docs/research/2026-08-25-europass-api-shapes.md). Without it the
    # render below converts an empty document and returns a blank PDF.
    _call(
        jar,
        "PUT",
        f"{_API_ROOT}/eprofile/cv/{quote(cv_id, safe='')}",
        body=payload,
        transport=transport,
    )
    rendered = _call(
        jar,
        "POST",
        f"{_API_ROOT}/eprofile/cv/{quote(cv_id, safe='')}",
        body=payload,
        transport=transport,
    )
    token = _download_token(rendered)
    download = f"{_API_ROOT}/office/download/pdf/{quote(token, safe='')}"
    for attempt in range(_DOWNLOAD_ATTEMPTS):
        try:
            return _call(jar, "GET", download, accept="application/pdf", transport=transport)
        except EuropassNotReady:
            if attempt == _DOWNLOAD_ATTEMPTS - 1:
                raise
            sleep(_DOWNLOAD_POLL_SECONDS)
    raise EuropassUnavailable("unreachable")  # pragma: no cover


_ATTACHMENT_NAME = "attachment.xml"
#: Two markers from a genuine Candidate document. Matched as bytes rather
#: than parsed: these arrive from a third party, an XML parser on third-party
#: bytes is an XXE surface, and the question here ("is this a Europass
#: document or an error page?") does not need a parse tree to answer.
_PROVENANCE_MARKERS = (
    b'schemeAgencyName="EUROPASS"',
    b"http://www.europass.eu/1.0",
)


def assert_europass_provenance(pdf_bytes: bytes) -> None:
    """Refuse a PDF that is not a genuine Europass document.

    Deliberately does NOT check that the XML's name matches the content's.
    europa.eu is the authority on what it rendered; re-litigating its output
    field by field would be a second mapper with no owner.
    """
    try:
        attachments = PdfReader(BytesIO(pdf_bytes)).attachments
    except Exception as error:  # pypdf raises several unrelated types here
        raise EuropassProvenanceMissing("not a readable PDF") from error
    payloads = attachments.get(_ATTACHMENT_NAME) or ()
    if not payloads:
        raise EuropassProvenanceMissing(f"PDF carries no {_ATTACHMENT_NAME}")
    xml = payloads[0]
    missing = [marker for marker in _PROVENANCE_MARKERS if marker not in xml]
    if missing:
        raise EuropassProvenanceMissing(f"{_ATTACHMENT_NAME} is not a Europass Candidate document")
