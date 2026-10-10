import io
import json
import pathlib
from datetime import date
from unittest import mock

import pytest

from apps.documents.europass import (
    EUROPASS_ORIGIN,
    EuropassProvenanceMissing,
    EuropassUnavailable,
    _call,
    _name_parts,
    assert_europass_provenance,
    europass_payload,
    render_europass_pdf,
)
from apps.documents.schemas import (
    AwardEntry,
    CVContent,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    PersonalInformation,
    PublicationEntry,
    ResearchEntry,
    SkillEntry,
    TimelineEntry,
)
from apps.research.egress import ResolvedTarget, UnsafeTarget

_FAKE_TARGET = ResolvedTarget(scheme="https", host="europa.eu", port=443, addresses=("93.184.1.1",))


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """_call runs the real validate_public_url, which resolves europa.eu.
    CI must not depend on live DNS, so the resolution is stubbed and the
    security property is pinned separately by the test below that keeps the
    real validator."""
    monkeypatch.setattr("apps.documents.europass.validate_public_url", lambda url: _FAKE_TARGET)


class _FakeResponse:
    def __init__(self, status, headers, body):
        self.status = status
        self.headers = _FakeHeaders(headers)
        self._body = body
        self.released = False

    def read(self, amount, decode_content=True):
        chunk, self._body = self._body[:amount], self._body[amount:]
        return chunk

    def release_conn(self):
        self.released = True


class _FakeHeaders(dict):
    def getlist(self, name):
        value = self.get(name)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]


def _transport(status=200, headers=None, body=b"{}"):
    """Records what it was asked to send, and the responses it returned, so
    the tests can assert on both what happened and what state was left
    behind (e.g. whether the connection was released)."""
    sent = []
    responses = []

    def call(target, *, method, path, body_bytes, headers_out):
        sent.append(
            {
                "host": target.host,
                "scheme": target.scheme,
                "method": method,
                "path": path,
                "body": body_bytes,
                "headers": headers_out,
            }
        )
        response = _FakeResponse(
            status, {"Content-Type": "application/json", **(headers or {})}, body
        )
        responses.append(response)
        return response

    call.sent = sent
    call.responses = responses
    return call


def test_call_echoes_the_xsrf_cookie_as_a_header():
    """The API rejects mutating calls whose X-XSRF-TOKEN header does not match
    the cookie it issued. This is the whole reason a cookie jar exists here."""
    transport = _transport()
    jar = {"XSRF-TOKEN": "tok-123"}
    _call(jar, "POST", "/x", body={"a": 1}, transport=transport)
    assert transport.sent[0]["headers"]["X-XSRF-TOKEN"] == "tok-123"


def test_call_absorbs_set_cookie_into_the_jar():
    transport = _transport(headers={"Set-Cookie": ["XSRF-TOKEN=abc; Path=/", "S=1; Path=/"]})
    jar = {}
    _call(jar, "GET", "/x", transport=transport)
    assert jar == {"XSRF-TOKEN": "abc", "S": "1"}


def test_call_sends_the_jar_back_as_a_cookie_header():
    transport = _transport()
    _call({"S": "1", "XSRF-TOKEN": "t"}, "GET", "/x", transport=transport)
    assert transport.sent[0]["headers"]["Cookie"] == "S=1; XSRF-TOKEN=t"


def test_call_raises_on_an_http_error():
    with pytest.raises(EuropassUnavailable):
        _call({}, "GET", "/x", transport=_transport(status=500))


def test_call_refuses_a_redirect_instead_of_following_it():
    """These are four known endpoints. A redirect means the API moved, which
    should surface as a failure rather than be chased somewhere unvalidated."""
    with pytest.raises(EuropassUnavailable):
        _call({}, "GET", "/x", transport=_transport(status=302, headers={"Location": "/y"}))


def test_call_refuses_an_unexpected_content_type():
    transport = _transport(headers={"Content-Type": "text/html"}, body=b"<html>")
    with pytest.raises(EuropassUnavailable, match="expected application/json, got text/html"):
        _call({}, "GET", "/x", transport=transport)


def test_call_refuses_a_response_over_the_cap():
    """Content-Type must match `accept` or _call raises for that reason before
    ever reaching the size loop -- so the transport's Content-Type has to be
    application/pdf here, and the raised reason is asserted, not just the
    exception type, so this can't silently start passing for the wrong
    reason again."""
    from apps.documents import europass

    transport = _transport(
        headers={"Content-Type": "application/pdf"},
        body=b"x" * (europass._MAX_BYTES + 1),
    )
    with pytest.raises(EuropassUnavailable, match="exceeded"):
        _call({}, "GET", "/x", accept="application/pdf", transport=transport)


def test_call_refuses_a_non_https_target(monkeypatch):
    """The scheme check in _call is otherwise untested: every other test's
    fake target is https because _no_dns pins it there."""
    http_target = ResolvedTarget(
        scheme="http", host="europa.eu", port=80, addresses=("93.184.1.1",)
    )
    monkeypatch.setattr("apps.documents.europass.validate_public_url", lambda url: http_target)
    with pytest.raises(EuropassUnavailable):
        _call({}, "GET", "/x", transport=_transport())


def test_call_always_releases_the_connection():
    """Proves the finally: response.release_conn() actually runs on the
    error path -- not just that the call happened."""
    transport = _transport(status=500)
    with pytest.raises(EuropassUnavailable):
        _call({}, "GET", "/x", transport=transport)
    assert transport.responses[0].released is True


def test_the_origin_is_a_pinned_https_europa_eu_url():
    assert EUROPASS_ORIGIN == "https://europa.eu"


def test_a_non_global_host_is_refused_by_validation():
    """Pins that validate_public_url is what guards this module. The worker
    this runs in is the environment _no_fetch was written to defend:
    169.254.170.2 hands out the task role's credentials."""
    from apps.research.egress import validate_public_url

    with pytest.raises(UnsafeTarget):
        validate_public_url("http://169.254.170.2/v2/credentials")


def _content(**overrides):
    base = dict(
        personal_information=PersonalInformation(
            full_name="Leyla Memmedova", email="leyla@apply.example"
        ),
        education=(
            EducationEntry(
                degree_as_awarded="BSc Computer Science",
                institution_original="Baku State University",
                city="Baku",
                country="AZ",
                start_date=date(2017, 9, 15),
                end_date=date(2021, 6, 30),
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


def test_name_splits_on_the_last_token():
    assert _name_parts("Leyla Memmedova") == ("Leyla", "Memmedova")
    assert _name_parts("Maria del Carmen Garcia") == ("Maria del Carmen", "Garcia")


def test_a_single_token_name_keeps_an_empty_family_name():
    """Better an empty box than a fabricated surname. The student sees this
    at the approval gate, which is the whole justification for splitting."""
    assert _name_parts("Prince") == ("Prince", "")


def test_the_payload_carries_the_split_name():
    payload = europass_payload(_content())
    personal = payload["profile"]["personalInformation"]
    assert personal["firstName"] == "Leyla"
    assert personal["lastName"] == "Memmedova"
    assert personal["emails"] == ["leyla@apply.example"]


def test_a_stated_phone_is_still_sent_as_an_empty_list():
    """R-9: the captured editor session never populated a phone number, so
    the entry shape is unverified. A wrong guess 500s the whole render, so
    the field is dropped even when the student gave us one -- this test is
    what stops someone "helpfully" mapping it back in without a capture."""
    content = _content(
        personal_information=PersonalInformation(
            full_name="Leyla Memmedova", email="leyla@apply.example", phone="+994501234567"
        )
    )
    personal = europass_payload(content)["profile"]["personalInformation"]
    assert personal["phones"] == []


def test_a_stated_date_of_birth_is_still_sent_as_null():
    """Same rule as phones (R-9): the captured session never populated
    dateOfBirth, so its shape is equally unverified and is dropped rather
    than guessed."""
    content = _content(
        personal_information=PersonalInformation(
            full_name="Leyla Memmedova",
            email="leyla@apply.example",
            date_of_birth=date(1999, 3, 4),
        )
    )
    personal = europass_payload(content)["profile"]["personalInformation"]
    assert personal["dateOfBirth"] is None


def test_a_stated_sex_is_still_sent_as_an_empty_string():
    """R-12: sex is free text on our side, codification-driven on europa.eu's,
    and the only value ever captured was the empty string -- same risk class
    as phone/dateOfBirth. Dropped even when the student gave us one."""
    content = _content(
        personal_information=PersonalInformation(
            full_name="Leyla Memmedova", email="leyla@apply.example", sex="female"
        )
    )
    personal = europass_payload(content)["profile"]["personalInformation"]
    assert personal["sex"] == ""


def test_a_mother_tongue_goes_to_native_and_the_rest_to_other():
    content = _content(
        languages=(
            LanguageEntry(language="Azerbaijani", cefr_level="C2", mother_tongue=True),
            LanguageEntry(language="English", cefr_level="C1", reading="C2"),
        )
    )
    skills = europass_payload(content)["profile"]["languageSkills"]
    assert [entry["language"] for entry in skills["nativeLanguages"]] == ["aze"]
    assert [entry["language"] for entry in skills["otherLanguages"]] == ["eng"]


def test_a_native_language_entry_carries_no_cefr_columns():
    """The real shape: nativeLanguages entries have no listening/reading/etc
    keys at all -- only otherLanguages entries do (task-4b-report.md)."""
    content = _content(
        languages=(LanguageEntry(language="Azerbaijani", cefr_level="C2", mother_tongue=True),)
    )
    entry = europass_payload(content)["profile"]["languageSkills"]["nativeLanguages"][0]
    assert entry == {
        "languageCategory": "NORMAL",
        "language": "aze",
        "mediaAttachments": [],
    }


def test_the_language_grid_uses_the_self_assessment_fallback():
    """One stated level fills five columns -- the rule spec 1 built. If the
    mapper read cefr_level directly, a refined sub-skill would be dropped."""
    content = _content(
        languages=(LanguageEntry(language="English", cefr_level="C1", reading="C2"),)
    )
    entry = europass_payload(content)["profile"]["languageSkills"]["otherLanguages"][0]
    assert entry["listening"] == "C1"
    assert entry["reading"] == "C2"
    assert entry["spokenInteraction"] == "C1"
    assert entry["writing"] == "C1"


def test_research_maps_to_projects():
    """Pins the spec's decision. Projects is first-class in Candidate.xsd and
    survives into the embedded XML; a custom section has no guaranteed
    mapping, which would degrade the provenance this whole path exists for."""
    content = _content(
        research=(ResearchEntry(thesis_title="On Graph Sparsifiers", supervisor="Prof. M"),)
    )
    projects = europass_payload(content)["profile"]["projects"]
    assert len(projects) == 1
    assert "On Graph Sparsifiers" in json.dumps(projects[0])


def test_an_unmappable_language_raises_rather_than_vanishing():
    """No fallback means no silent omission either. A Europass CV missing a
    language the student declared is worse than a loud failure, and the fix
    is one dict entry."""
    content = _content(languages=(LanguageEntry(language="Klingon", cefr_level="C2"),))
    with pytest.raises(EuropassUnavailable):
        europass_payload(content)


#: The exact set of profile-level sections this mapper produces. A literal,
#: not derived from the fixture, so dropping a section from europass_payload
#: fails here even though the fixture itself has many more (unmapped) keys.
_EXPECTED_PROFILE_KEYS = frozenset(
    {
        "language",
        "personalInformation",
        "workExperiences",
        "educationTrainings",
        "languageSkills",
        "projects",
        "publications",
        "honoursAwards",
        "profileSkills",
        "preference",
        "skillsAssessment",
        "customSections",
    }
)


def test_the_payload_shape_matches_the_captured_fixture():
    """The fixture is what europa.eu actually returned. This is the test that
    catches the undocumented API renaming a section under us -- checked in
    both directions: a dropped section fails the literal-set comparison, and
    a section the real API renamed fails the fixture comparison."""
    fixture = json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "europass_profile.json").read_text()
    )
    produced = europass_payload(_content())
    assert set(produced["profile"]) == _EXPECTED_PROFILE_KEYS
    assert _EXPECTED_PROFILE_KEYS <= set(fixture["profile"])


def test_education_country_is_lowercased_for_europass():
    """CVContent.country is uppercase ISO 3166-1 alpha-2; europa.eu wants it
    lowercase (task-4b-report.md)."""
    entry = europass_payload(_content())["profile"]["educationTrainings"][0]
    assert entry["country"] == "az"


def test_render_writes_the_profile_before_rendering_it():
    """The create POST silently drops every content section.

    europass_profile.json is a GET readback taken immediately after create,
    and it shows educationTrainings, languageSkills and every other section
    empty even though the canary's payload carries them -- create honours
    only personalInformation's name/email and the template block. PUT is the
    write path that persists sections (verified round-trip in
    docs/research/2026-08-25-europass-api-shapes.md), so a sequence that
    never PUTs renders an empty document: a one-page PDF with a name on it.
    """
    calls = []

    def transport(target, *, method, path, body_bytes, headers_out):
        calls.append((method, path, body_bytes))
        if path.endswith("/frontend-config"):
            body = b"{}"
        elif path.endswith("/eprofile/cv"):
            body = b'{"id": "cv-1"}'
        elif "/office/download/pdf/" in path:
            return _FakeResponse(200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 ...")
        elif method == "PUT":
            # A real PUT answers with the id alone, not the document.
            body = b'{"id": "cv-1"}'
        else:
            # The real key observed from europa.eu's render call is "id",
            # not "hash" -- this is the only test of the live call sequence,
            # so it should use a shape the API actually returns.
            body = b'{"id": "h-1"}'
        return _FakeResponse(200, {"Content-Type": "application/json"}, body)

    pdf = render_europass_pdf(_content(), transport=transport)
    assert pdf.startswith(b"%PDF")
    # M-1: the method matters as much as the path -- create is POST, the
    # write is PUT, the render call is POST again, and a mutation of any of
    # them must turn this test red, not just a mutation of the path.
    assert [(method, path) for method, path, _ in calls] == [
        ("GET", "/europass/eportfolio/api/frontend-config"),
        ("POST", "/europass/eportfolio/api/eprofile/cv"),
        ("PUT", "/europass/eportfolio/api/eprofile/cv/cv-1"),
        ("POST", "/europass/eportfolio/api/eprofile/cv/cv-1"),
        ("GET", "/europass/eportfolio/api/office/download/pdf/h-1"),
    ]
    written = json.loads(next(body for method, _, body in calls if method == "PUT"))
    assert written["profile"]["educationTrainings"], "PUT must carry the sections"


def test_payload_names_the_sections_the_renderer_must_print():
    """europa.eu prints only the sections listed in profileStructure.

    An empty list renders a one-page PDF carrying the name and email and
    nothing else -- the whole profile is stored, and simply not drawn. The
    keys are the editor's own kebab-case section ids; camelCase spellings
    round-trip through the API untouched and are then ignored, so this
    asserts the literal keys, not merely that the list is non-empty.
    """
    structure = europass_payload(_content())["profile"]["preference"]["profileStructure"]
    assert "education-training" in structure
    assert "work-experience" in structure
    assert structure[0] == "personal-information"
    assert not [key for key in structure if key != key.lower() or "_" in key]


def test_render_polls_a_download_that_is_not_ready_yet():
    """The document office renders asynchronously: the first download after
    a render routinely answers 204 with no body, and the PDF a moment
    later. Treating that as a failure throws away a good render."""
    attempts = []

    def transport(target, *, method, path, body_bytes, headers_out):
        if path.endswith("/frontend-config"):
            return _FakeResponse(200, {"Content-Type": "application/json"}, b"{}")
        if path.endswith("/eprofile/cv"):
            return _FakeResponse(200, {"Content-Type": "application/json"}, b'{"id": "cv-1"}')
        if "/office/download/pdf/" in path:
            attempts.append(path)
            if len(attempts) < 3:
                return _FakeResponse(204, {}, b"")
            return _FakeResponse(200, {"Content-Type": "application/pdf"}, b"%PDF-1.4 ...")
        return _FakeResponse(200, {"Content-Type": "application/json"}, b'{"id": "h-1"}')

    with mock.patch("apps.documents.europass.sleep") as slept:
        pdf = render_europass_pdf(_content(), transport=transport)
    assert pdf.startswith(b"%PDF")
    assert len(attempts) == 3
    assert slept.call_count == 2


def test_render_gives_up_on_a_download_that_never_becomes_ready():
    def transport(target, *, method, path, body_bytes, headers_out):
        if path.endswith("/frontend-config"):
            return _FakeResponse(200, {"Content-Type": "application/json"}, b"{}")
        if path.endswith("/eprofile/cv"):
            return _FakeResponse(200, {"Content-Type": "application/json"}, b'{"id": "cv-1"}')
        if "/office/download/pdf/" in path:
            return _FakeResponse(204, {}, b"")
        return _FakeResponse(200, {"Content-Type": "application/json"}, b'{"id": "h-1"}')

    with mock.patch("apps.documents.europass.sleep"):
        with pytest.raises(EuropassUnavailable):
            render_europass_pdf(_content(), transport=transport)


def test_render_raises_when_create_returns_no_id():
    def transport(target, *, method, path, body_bytes, headers_out):
        return _FakeResponse(200, {"Content-Type": "application/json"}, b"{}")

    with pytest.raises(EuropassUnavailable):
        render_europass_pdf(_content(), transport=transport)


# --- I-2: the module's docstring says EuropassUnavailable covers every
# failure mode; these pin the three paths that previously escaped raw.


def test_call_wraps_a_transport_failure_as_europass_unavailable():
    """A network timeout is the single most likely production failure of
    this module. render.py's caller reasonably does `except
    EuropassUnavailable`, so a raw urllib3 exception escaping here would go
    uncaught."""
    import urllib3

    def transport(target, *, method, path, body_bytes, headers_out):
        raise urllib3.exceptions.ReadTimeoutError(None, path, "read timed out")

    with pytest.raises(EuropassUnavailable):
        _call({}, "GET", "/x", transport=transport)


def test_call_wraps_an_unsafe_target_as_europass_unavailable(monkeypatch):
    """UnsafeTarget from validate_public_url must not escape raw either --
    same contract as any other failure this module produces."""

    def _refuse(url):
        raise UnsafeTarget("refused: not a public address")

    monkeypatch.setattr("apps.documents.europass.validate_public_url", _refuse)
    with pytest.raises(EuropassUnavailable):
        _call({}, "GET", "/x", transport=_transport())


def test_call_wraps_a_mid_body_read_timeout_as_europass_unavailable():
    """The transport callable succeeds; the failure happens later, in the
    streaming read loop (preload_content=False means that loop is where
    most of the wire time is spent). This is the path the reviewer proved
    still escaped raw -- the sibling test above only raises from transport
    itself, which was already covered."""
    import urllib3

    class _TimeoutOnRead(_FakeResponse):
        def read(self, amount, decode_content=True):
            raise urllib3.exceptions.ReadTimeoutError(None, "/x", "read timed out")

    def transport(target, *, method, path, body_bytes, headers_out):
        response = _TimeoutOnRead(200, {"Content-Type": "application/json"}, b"{}")
        transport.response = response
        return response

    with pytest.raises(EuropassUnavailable):
        _call({}, "GET", "/x", transport=transport)
    assert transport.response.released is True


def test_render_raises_when_the_create_response_is_not_json():
    """_download_token already guards json.loads this way; the create-call
    site in render_europass_pdf was unguarded until this fix -- the two must
    behave the same way on a malformed create response."""

    def transport(target, *, method, path, body_bytes, headers_out):
        if path.endswith("/frontend-config"):
            return _FakeResponse(200, {"Content-Type": "application/json"}, b"{}")
        return _FakeResponse(200, {"Content-Type": "application/json"}, b"not json")

    with pytest.raises(EuropassUnavailable):
        render_europass_pdf(_content(), transport=transport)


def test_render_raises_when_the_create_response_is_non_utf8_bytes():
    """json.loads(b"\\x80abc") raises UnicodeDecodeError, a ValueError but
    not a JSONDecodeError -- realistic for a truncated or gzipped error page
    served with Content-Type: application/json. The create-response guard
    must catch ValueError, not just json.JSONDecodeError."""

    def transport(target, *, method, path, body_bytes, headers_out):
        if path.endswith("/frontend-config"):
            return _FakeResponse(200, {"Content-Type": "application/json"}, b"{}")
        return _FakeResponse(200, {"Content-Type": "application/json"}, b"\x80abc")

    with pytest.raises(EuropassUnavailable):
        render_europass_pdf(_content(), transport=transport)


def test_download_token_raises_on_non_utf8_bytes():
    """Same defect, direct on _download_token: a JSONDecodeError-only guard
    lets UnicodeDecodeError escape raw."""
    from apps.documents.europass import _download_token

    with pytest.raises(EuropassUnavailable):
        _download_token(b"\x80abc")


# --- I-1: one literal, fully-populated entry per section. The point is that
# mutating any key name or value shape in the mapper turns one of these red;
# see task-5-report.md's "fix round 2" section for the mutation proof.


def test_the_other_language_entry_matches_the_captured_shape_literally():
    content = _content(
        languages=(LanguageEntry(language="English", cefr_level="C1", reading="C2"),)
    )
    entry = europass_payload(content)["profile"]["languageSkills"]["otherLanguages"][0]
    assert entry == {
        "languageCategory": "NORMAL",
        "language": "eng",
        "listening": "C1",
        "reading": "C2",
        "spokenInteraction": "C1",
        "spokenProduction": "C1",
        "writing": "C1",
        "mediaAttachments": [],
    }


def test_an_other_language_with_no_stated_level_omits_the_cefr_keys():
    """M-2: a null sub-skill value was never observed in the capture -- only
    a string, or the key's complete absence (as on native entries). A
    language with no cefr_level and no per-skill override must omit the
    keys, not send them as null."""
    content = _content(languages=(LanguageEntry(language="English"),))
    entry = europass_payload(content)["profile"]["languageSkills"]["otherLanguages"][0]
    assert entry == {
        "languageCategory": "NORMAL",
        "language": "eng",
        "mediaAttachments": [],
    }


def test_the_education_entry_matches_the_captured_shape_literally():
    entry = europass_payload(_content())["profile"]["educationTrainings"][0]
    assert entry == {
        "order": 0,
        "qualification": "BSc Computer Science",
        "organisationName": "Baku State University",
        "streetAddress": None,
        "postalCode": None,
        "city": "Baku",
        "country": "az",
        "website": None,
        "creationDate": None,
        "startDate": {"date": "2017-09-15", "dateType": "DAY", "empty": False},
        "endDate": {"date": "2021-06-30", "dateType": "DAY", "empty": False},
        "ongoing": False,
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


def test_the_work_experience_entry_matches_the_captured_shape_literally():
    """Pins the nested employerDetails/workExperience structure -- a mutation
    that flattens it, or renames either wrapper key, must fail here."""
    content = _content(
        experience=(
            ExperienceEntry(
                employer="Acme GmbH",
                title="Backend Engineer",
                city="Berlin",
                country="DE",
                start_date=date(2021, 7, 1),
                bullets=("Built payment services.",),
            ),
        )
    )
    entry = europass_payload(content)["profile"]["workExperiences"]["solidWorkExperiences"][0]
    assert entry == {
        "order": 0,
        "employerDetails": {
            "employer": "Acme GmbH",
            "organisationDepartment": None,
            "organisationBusinessSector": None,
            "organisationWebsite": None,
            "organisationContactEmail": None,
            "organisationAddress": {
                "addressPart1": "",
                "addressPart2": "",
                "postalCode": "",
                "city": "Berlin",
                "country": "de",
            },
        },
        "workExperience": {
            "occupation": {"label": "Backend Engineer", "uri": None},
            "creationDate": None,
            "startDate": {"date": "2021-07-01", "dateType": "DAY", "empty": False},
            "endDate": None,
            "ongoing": True,
            "mainActivities": "Built payment services.",
            "mediaAttachments": None,
            "links": None,
            "groupReference": None,
        },
    }


def test_the_project_entry_matches_the_captured_shape_literally():
    content = _content(
        research=(
            ResearchEntry(
                thesis_title="On Graph Sparsifiers",
                supervisor="Prof. M",
                methods="Spectral techniques",
                outcomes="Improved bounds",
            ),
        )
    )
    entry = europass_payload(content)["profile"]["projects"][0]
    assert entry == {
        "order": 0,
        "title": "On Graph Sparsifiers",
        "description": "Prof. M Spectral techniques Improved bounds",
        "creationDate": None,
        "startDate": None,
        "endDate": None,
        "ongoing": False,
        "mediaAttachments": None,
        "links": None,
    }


def test_the_publication_entry_matches_the_captured_shape_literally():
    content = _content(
        publications=(
            PublicationEntry(
                authors=("Doe, J.", "Roe, R."),
                self_author_index=0,
                title="Sparsifiers in practice",
                venue="Journal of Examples",
                year=2024,
                doi="10.1000/sparsifiers",
            ),
        )
    )
    entry = europass_payload(content)["profile"]["publications"][0]
    assert entry == {
        "order": 0,
        "title": "Sparsifiers in practice",
        "creationDate": None,
        "year": "2024",
        "reference": None,
        "doi": "10.1000/sparsifiers",
        "description": None,
        "mediaAttachments": None,
        "links": None,
        "authors": "Doe, J., Roe, R.",
        "journalConference": "Journal of Examples",
        "publisher": None,
        "volumeIssuePages": None,
    }


def test_the_award_entry_matches_the_captured_shape_literally():
    content = _content(awards=(AwardEntry(title="Best Thesis Award"),))
    entry = europass_payload(content)["profile"]["honoursAwards"][0]
    assert entry == {
        "order": 0,
        "title": "Best Thesis Award",
        "description": None,
        "institution": None,
        "creationDate": None,
        "date": None,
        "mediaAttachments": None,
        "links": None,
    }


def test_the_skill_entry_matches_the_captured_shape_literally():
    content = _content(skills=(SkillEntry(name="Python", category="Tools"),))
    other = europass_payload(content)["profile"]["profileSkills"]["other"]
    assert other == [{"type": "digitalSkill", "label": "Python"}]


def _genuine_pdf() -> bytes:
    return pathlib.Path("tests/documents/fixtures/europass_api.pdf").read_bytes()


def test_a_genuine_europass_pdf_passes():
    assert_europass_provenance(_genuine_pdf())


def test_our_own_render_fails_provenance():
    """The negative fixture is our own EUROPASS look-alike, which is exactly
    the document that must never pass as Europass."""
    from apps.documents.render import render_cv

    ours = render_cv(_content(), variant="EUROPASS").pdf_bytes
    with pytest.raises(EuropassProvenanceMissing):
        assert_europass_provenance(ours)


def test_unreadable_bytes_fail_provenance():
    with pytest.raises(EuropassProvenanceMissing):
        assert_europass_provenance(b"not a pdf at all")


def _pdf_with_attachment(name: str, data: bytes) -> bytes:
    """Build a minimal PDF carrying an embedded file, for provenance tests
    that need a document shape (not merely unreadable bytes)."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_attachment(name, data)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_a_pdf_with_an_attachment_xml_that_is_not_europass_fails_provenance():
    """The case the whole check exists to catch: a PDF that carries an
    attachment.xml, so it is not "no attachment at all", but whose bytes are
    not a genuine Europass Candidate document. The prior negative tests only
    covered unreadable bytes and a missing attachment -- neither exercises
    the marker check itself."""
    pdf_bytes = _pdf_with_attachment("attachment.xml", b"<root>not a europass document</root>")
    with pytest.raises(EuropassProvenanceMissing, match="not a Europass Candidate document"):
        assert_europass_provenance(pdf_bytes)


def test_scrubbing_metadata_preserves_the_attachment():
    """Pins an empirical finding. scrub_pdf_metadata runs on every released
    artefact; if a change to it ever stripped embedded files, every Europass
    CV would lose its provenance silently."""
    from apps.documents.hygiene import scrub_pdf_metadata

    assert_europass_provenance(scrub_pdf_metadata(_genuine_pdf()))


def test_a_429_raises_throttled_with_the_retry_after_seconds():
    from apps.documents.europass import EuropassThrottled

    transport = _transport(status=429, headers={"Retry-After": "120"})
    with pytest.raises(EuropassThrottled) as excinfo:
        _call({}, "GET", "/x", transport=transport)
    assert excinfo.value.retry_after_seconds == 120


def test_a_429_without_retry_after_uses_the_default():
    """A throttle with no hint still has to pause us, or we keep hammering."""
    from apps.documents.europass import _DEFAULT_RETRY_AFTER_SECONDS, EuropassThrottled

    transport = _transport(status=429)
    with pytest.raises(EuropassThrottled) as excinfo:
        _call({}, "GET", "/x", transport=transport)
    assert excinfo.value.retry_after_seconds == _DEFAULT_RETRY_AFTER_SECONDS


def test_a_garbage_retry_after_uses_the_default():
    from apps.documents.europass import _DEFAULT_RETRY_AFTER_SECONDS, EuropassThrottled

    transport = _transport(status=429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    with pytest.raises(EuropassThrottled) as excinfo:
        _call({}, "GET", "/x", transport=transport)
    assert excinfo.value.retry_after_seconds == _DEFAULT_RETRY_AFTER_SECONDS


def test_throttled_is_still_a_europass_unavailable():
    """Callers written against the documented contract must keep working."""
    from apps.documents.europass import EuropassThrottled, EuropassUnavailable

    assert issubclass(EuropassThrottled, EuropassUnavailable)


def test_a_locationless_role_sends_empty_strings_not_nulls():
    """ExperienceEntry.city/country are optional; organisationAddress is not.

    A real CV names the employer but not the town for most roles, so this is
    the ordinary case, not an edge one. The three sibling address keys already
    send "" for an absent part; a null here is a shape this API has never been
    observed to accept, and _language_entry's six HTTP 500s are what guessing
    costs. No local test can catch a rejected payload -- nothing here talks to
    europa.eu -- so the shape is pinned instead.
    """
    content = _content(
        experience=(
            ExperienceEntry(
                employer="EPFL",
                title="Research Intern",
                start_date=date(2025, 9, 1),
                bullets=("Benchmarked generative models.",),
            ),
        )
    )
    address = europass_payload(content)["profile"]["workExperiences"]["solidWorkExperiences"][0][
        "employerDetails"
    ]["organisationAddress"]
    assert address == {
        "addressPart1": "",
        "addressPart2": "",
        "postalCode": "",
        "city": "",
        "country": "",
    }
    assert None not in address.values()


def test_a_degree_with_no_country_sends_none_rather_than_crashing():
    """country became optional on 2026-08-31 -- a US CV names no country and a
    required field made the model invent one. Europass takes a null for a
    field the document never stated; it must not take a traceback."""
    content = _content()
    education = content.education[0].model_copy(update={"country": None, "city": None})
    entry = europass_payload(content.model_copy(update={"education": (education,)}))[
        "profile"
    ]["educationTrainings"][0]
    assert entry["country"] is None
    assert entry["city"] is None


def test_a_gap_statement_is_a_europass_work_experience():
    """Owner decision 2026-10-06: europa.eu prints the same history the CV
    does. A gap row goes into the captured work-experience shape -- the
    statement as the occupation, no employer -- in date order with the posts.
    """
    post = ExperienceEntry(
        employer="ICIQ",
        title="Research Intern",
        start_date="2023-11-01",
        end_date="2024-02-29",
        bullets=("Ran a screen of forty catalysts.",),
    )
    content = _content(
        experience=(post,),
        timeline=(
            TimelineEntry(
                start_date="2023-06-30",
                end_date="2023-11-01",
                statement="Full-time carer for a family member.",
            ),
        ),
    )

    rows = europass_payload(content)["profile"]["workExperiences"]["solidWorkExperiences"]

    assert [r["workExperience"]["occupation"]["label"] for r in rows] == [
        "Research Intern",
        "Full-time carer for a family member.",
    ]
    assert [r["order"] for r in rows] == [0, 1]
    gap = rows[1]
    assert gap["employerDetails"]["employer"] == ""
    assert gap["workExperience"]["mainActivities"] == ""
    assert gap["workExperience"]["ongoing"] is False


def test_a_cv_without_gap_rows_sends_the_posts_unchanged():
    post = ExperienceEntry(
        employer="ICIQ", title="Research Intern", start_date="2023-11-01", bullets=("A.",)
    )
    content = _content(experience=(post,))

    rows = europass_payload(content)["profile"]["workExperiences"]["solidWorkExperiences"]

    assert [r["employerDetails"]["employer"] for r in rows] == ["ICIQ"]


def test_gap_rows_follow_an_oldest_first_programme_into_europass():
    """A programme asking for oldest first gets its gap rows in that order too:
    the posts arrive already ordered by render's funnel, and the merge must not
    flip the run back to newest first."""
    earlier = ExperienceEntry(
        employer="ICIQ", title="Research Intern", start_date="2023-11-01",
        end_date="2024-02-29", bullets=("A.",),
    )
    later = ExperienceEntry(
        employer="EPFL", title="Assistant", start_date="2024-06-01", bullets=("B.",),
    )
    content = _content(
        experience=(earlier, later),
        timeline=(
            TimelineEntry(
                start_date="2023-06-30", end_date="2023-11-01",
                statement="Full-time carer for a family member.",
            ),
        ),
    )

    rows = europass_payload(content, oldest_first=True)["profile"]["workExperiences"][
        "solidWorkExperiences"
    ]

    assert [r["workExperience"]["occupation"]["label"] for r in rows] == [
        "Full-time carer for a family member.",
        "Research Intern",
        "Assistant",
    ]
