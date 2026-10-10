"""Exercise the live Europass API. Capture its profile document, or check it.

    uv run python manage.py europass_canary --capture   # refresh the fixture
    uv run python manage.py europass_canary             # canary: does it work?

This talks to a third party over the network. It is deliberately NOT a test:
an undocumented API that changes shape must page someone, but it must never
fail a pull request that did not touch this code.
"""

from __future__ import annotations

import json
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from django.core.management.base import BaseCommand, CommandError, CommandParser
from pypdf import PdfReader

from apps.documents.europass import (
    _API_ROOT,
    EuropassUnavailable,
    _call,
    assert_europass_provenance,
    europass_payload,
    render_europass_pdf,
)
from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    ExperienceEntry,
    LanguageEntry,
    PersonalInformation,
    TimelineEntry,
)

FIXTURE = Path("tests/documents/fixtures/europass_profile.json")

#: Synthetic-only data (never a real student's) that exercises every section
#: europass_payload maps, run through the same mapper production uses -- a
#: hand-rolled skeleton previously diverged from what europass_payload
#: actually produces (birthPlace vs birthplace, a string "false" instead of
#: a bool, extra preference.id/profileId) and shipped an empty
#: languageSkills, the one section that produced six HTTP 500s (see
#: task-4b-report.md). This is "the entire early-warning system" for an
#: undocumented API, so it must send what production actually sends.
_CANARY_DEGREE = "BSc Computer Science"
_CANARY_EMPLOYER = "Example Institute"
#: A gap row goes to europa.eu as a work experience with an empty employer
#: (europass._gap_entry). That shape is the canary's to prove: no unit test
#: talks to the API, and a rejected shape fails the student's whole CV.
_CANARY_GAP = "Canary gap statement."

_CANARY_CONTENT = CVContent(
    personal_information=PersonalInformation(
        full_name="Canary Probe", email="canary@example.invalid"
    ),
    education=(
        EducationEntry(
            degree_as_awarded=_CANARY_DEGREE,
            institution_original="Example University",
            city="Example City",
            country="AZ",
            start_date=date(2017, 9, 1),
            end_date=date(2021, 6, 30),
        ),
    ),
    experience=(
        # Deliberately no city/country. Both are optional on ExperienceEntry
        # because a real CV names the employer but not the town for most
        # roles, so europass_payload sends "" for them -- a shape this API has
        # never been observed to accept, and the reason organisationAddress
        # must never carry a null. The canary is the only thing that can find
        # out; an empty `experience` tuple could not, which is how the shape
        # shipped unexercised in the first place.
        ExperienceEntry(
            employer=_CANARY_EMPLOYER,
            title="Research Intern",
            start_date=date(2021, 9, 1),
            end_date=date(2021, 12, 31),
            bullets=("Ran the canary.",),
        ),
    ),
    timeline=(
        TimelineEntry(
            start_date=date(2021, 6, 30), end_date=date(2021, 9, 1), statement=_CANARY_GAP
        ),
    ),
    research=(),
    publications=(),
    awards=(),
    skills=(),
    languages=(
        LanguageEntry(language="Azerbaijani", cefr_level="C2", mother_tongue=True),
        LanguageEntry(language="English", cefr_level="C1", reading="C2"),
    ),
    document_language="en",
)


class Command(BaseCommand):
    help = "Exercise the live Europass CV API; --capture refreshes the fixture."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--capture",
            action="store_true",
            help="Write the returned profile document to the committed fixture.",
        )

    def handle(self, *args: object, **options: object) -> None:
        payload = europass_payload(_CANARY_CONTENT)
        jar: dict[str, str] = {}
        try:
            _call(jar, "GET", f"{_API_ROOT}/frontend-config")
            created = json.loads(_call(jar, "POST", f"{_API_ROOT}/eprofile/cv", body=payload))
            cv_id = created.get("id")
            if not isinstance(cv_id, str) or not cv_id:
                raise CommandError(f"create returned no usable id: {created!r}")
            # Mirror production: create seeds an empty CV and silently drops
            # every content section, so without this PUT the readback below
            # describes a document nobody would recognise.
            _call(jar, "PUT", f"{_API_ROOT}/eprofile/cv/{quote(cv_id, safe='')}", body=payload)
            document = json.loads(
                _call(jar, "GET", f"{_API_ROOT}/eprofile/cv/{quote(cv_id, safe='')}")
            )
            # ponytail: this is a second guest CV -- render_europass_pdf runs
            # its own create/write/render. Reusing the one above would mean
            # widening that function's signature to hand back a cv id for a
            # caller that is not production. Two synthetic CVs per scheduled
            # run is the cheaper price. Upgrade path: if guest-CV retention
            # ever gets an answer from EMPL-ELM-SUPPORT that makes each one
            # expensive, thread the jar and id through instead.
            pdf = render_europass_pdf(_CANARY_CONTENT)
            assert_europass_provenance(pdf)
        except EuropassUnavailable as error:
            raise CommandError(f"Europass API failed: {error}") from error

        keys = sorted(document.get("profile", {}))
        self.stdout.write(f"profile keys: {keys}")
        # Provenance proves the PDF is a Europass document; it does not prove
        # the document contains anything. A blank render -- every section
        # stored server-side and none of them drawn -- passes every other
        # check this command makes, and did, for seventeen commits. This is
        # the check that fails when that happens again.
        text = "".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        # _CANARY_EMPLOYER is here for the same reason the other three are: the
        # locationless role sends "" for city and country, and a payload the
        # API accepts but silently drops would otherwise look identical to one
        # it stored. Acceptance is not rendering.
        for expected in (
            _CANARY_DEGREE,
            _CANARY_EMPLOYER,
            _CANARY_GAP,
            "Example University",
            "ENGLISH",
        ):
            if expected.casefold() not in text.casefold():
                raise CommandError(
                    f"rendered PDF is missing {expected!r} -- europa.eu rendered a "
                    f"document with {len(text)} characters of text on {len(text.splitlines())} "
                    "lines. Check preference.profileStructure and the PUT above."
                )
        self.stdout.write(self.style.SUCCESS(f"render carries {len(text)} characters of text"))
        if options.get("capture"):
            FIXTURE.parent.mkdir(parents=True, exist_ok=True)
            FIXTURE.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
            self.stdout.write(self.style.SUCCESS(f"wrote {FIXTURE}"))
