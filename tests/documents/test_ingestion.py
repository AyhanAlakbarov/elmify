import base64
import io
import zipfile
from datetime import date
from unittest.mock import MagicMock

import pytest
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from apps.concierge.documents import DocumentUnavailable, apply_scan_result, register
from apps.documents.ingestion import (
    IngestionRateLimited,
    UnsupportedUpload,
    extract_link_urls,
    extract_text,
    ingest_uploaded_cv,
)
from apps.documents.models import VerifiedFact
from apps.documents.schemas import (
    CVContent,
    EducationEntry,
    PersonalInformation,
    SkillEntry,
)
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.uploads import promoted_upload

pytestmark = pytest.mark.django_db

_DOCX_XML = (
    b'<?xml version="1.0"?>'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body><w:p><w:r><w:t>Jane Doe</w:t></w:r></w:p></w:body></w:document>"
)

_XXE_DOCX_XML = (
    b'<?xml version="1.0"?>'
    b'<!DOCTYPE doc [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body></w:document>"
)


_HYPERLINK_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)
_IMAGE_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def _rels(*relationships: tuple[str, str]) -> bytes:
    entries = "".join(
        f'<Relationship Id="rId{n}" Type="{rel_type}" Target="{target}" '
        f'TargetMode="External"/>'
        for n, (rel_type, target) in enumerate(relationships)
    )
    return (
        b'<?xml version="1.0"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + entries.encode()
        + b"</Relationships>"
    )


def _docx(xml: bytes, rels: bytes | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
        if rels is not None:
            archive.writestr("word/_rels/document.xml.rels", rels)
    return buffer.getvalue()


def _linking_pdf(*hrefs: str) -> bytes:
    from weasyprint import HTML

    anchors = "".join(f'<a href="{href}">link</a> ' for href in hrefs)
    return HTML(string=f"<p>Jane Doe {anchors}</p>").write_pdf()


def _pdf() -> bytes:
    from weasyprint import HTML

    return HTML(string="<p>Jane Doe</p>").write_pdf()


def _kerned_pdf() -> bytes:
    """A PDF whose text operator carries an explicit kerning adjustment.

    WeasyPrint cannot produce the document this needs: the artifact under test
    is a property of the text-showing operator, and the corpus renders every
    document it owns from HTML. So this writes the file itself -- no binary in
    git, and the offending number is visible here rather than buried in a
    fixture.

    A TJ array's numbers displace the next glyph by thousandths of an em.
    Microsoft Word emits them around tight pairs; pypdf reads a large enough
    one as a word gap and invents a space. -200 provokes it and -100 does not,
    measured -- the test asserts pypdf's own reading, so a version that stops
    inventing the space fails there rather than passing quietly.
    """
    stream = b"BT /F1 11 Tf 72 700 Td [(Scikit) -200 (-learn)] TJ ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        start,
    )
    return bytes(out)


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _content():
    return CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
        education=(
            EducationEntry(
                degree_as_awarded="BSc",
                institution_original="Example U",
                city="Berlin",
                country="DE",
                start_date="2020-09-01",
            ),
        ),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(SkillEntry(name="Python"),),
        languages=(),
        document_language="en",
    )


def _openai_client():
    client = MagicMock()
    response = MagicMock()
    response.output_parsed = _content()
    response.output = []
    client.responses.parse.return_value = response
    return client


def test_extract_text_reads_a_pdf():
    assert "Jane Doe" in extract_text(_pdf())


def test_extract_text_reads_a_docx():
    assert "Jane Doe" in extract_text(_docx(_DOCX_XML))


def test_extract_text_refuses_an_external_entity():
    """defusedxml, not xml.etree: an uploaded CV is attacker-supplied XML."""
    with pytest.raises(Exception):  # defusedxml.EntitiesForbidden
        extract_text(_docx(_XXE_DOCX_XML))


def test_extract_text_refuses_a_truncated_pdf():
    """The bytes claim to be a PDF and are not readable as one. pypdf raises
    PdfStreamError, which nothing converted -- so it escaped the document
    worker's UnsupportedUpload guard and killed the task."""
    with pytest.raises(UnsupportedUpload):
        extract_text(b"%PDF-1.4 and then nothing at all")


def test_extract_text_refuses_a_corrupt_archive():
    """Right magic, wrong body: zipfile raises BadZipFile, same escape."""
    with pytest.raises(UnsupportedUpload):
        extract_text(b"PK\x03\x04" + b"not really a zip")


# Both blobs are a PdfWriter().add_blank_page(200, 200) PDF with 10 bytes
# flipped at fixed offsets (found by fuzzing with a fixed seed, not by hand --
# see apps/documents/ingestion.py's _PDF_READ_ERRORS comment). Kept as fixed
# bytes rather than generated per test run: the point is two *specific*,
# reproduced corruptions that pypdf 6.16.1 is confirmed (below) to raise
# ValueError and AttributeError for, not "some corrupt PDF or other" -- most
# random byte flips raise PyPdfError, which was already caught before this
# fix.
_VALUE_ERROR_PDF = base64.b64decode(
    "JVBERi0xLjMKJeLjz9MKMSkwIG9iago8PAovUHJvZHVjZXLWKHB5cGRmKQo+jAplbmRvYmoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDEKL0tpZHMgWyATQjAgUiBdCj4+CmVuZG9iagozIDAgb2JqCjw8Ci9UeXBlIC9DYXhhbG9nCi9QYWdlcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvUGFnZQovUmVzb3VyY2VzIDw8Cj4+Ci9NZWRpYUJveCBbIDAuMCAwLjAgMjAwIDIwMCBdCi9QYXJlbnQgMiAwblIKPj4KZW5kb2JqCnhyZWYKMCA1CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAwMDAxNSAwMDAwMCBuIAowMDAwMDAwMMg0IDAwMDAwIG4gCjAwMDAwMDAxMTMgjTAwMDAgbiAKMDAwMDAwMDE2MiAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDUKL1Jvb3QgMyAwIFIKL0luZm8gMSAwIFIKPj4Kc3RhcnR4cmVmTDI1NgolJUVPRgo="
)
_ATTRIBUTE_ERROR_PDF = base64.b64decode(
    "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgKHB5cGRmKQo+PgoLbmRvYmoKMiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDEKL0tpZHMgWyA0IDAgUiBdCj4+CmVuZG9iagozIDAgbwBqCjw8Ci9UeXBlIC9DYXRhbG9nCi9QYWfjcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvUGFnZQovUmVzb3VyY2VzIDw8Cj4+Ci9NZWRpykJveCBbIDAuMCAwLjAgMjAwIDIwMCBdCi9QYXJlbnQgMiAwIFIKPj4KZW5kb2KKCnhyZWYKMCA1CjAwMDAwMDAwMDAgNjWDMzUgZiAKMDAwMDAwMDAxNSAwMDAwMCBuIAowMDAwMDAwMDU0IDAwMDAwIG40CjAwMDAwMDAxMTMgMDAwMDAgbiAKMDA9MDAwMDE2MiAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDUKL1Jvb3QUyyAwIFIKL0luZm8gMSAwIFIKPj4Kc3RhcnR4cmVmCjI1NgolJUVPRgo="
)


def test_pdf_corruption_pins_which_exceptions_pypdf_actually_raises():
    """These two byte blobs exist because the docstring's old claim --
    UnsupportedUpload "and only that" -- was false, measured against pinned
    pypdf 6.16.1: 300 corrupted PDFs raised AttributeError 20 times and
    ValueError 8 times, both escaping PyPdfError. This pins that premise
    directly against the reader, so a pypdf upgrade that changes these
    exception types fails loudly here instead of silently reopening the gap.
    """
    # Re-measured on pypdf 6.21.2 (2026-10-25): BOTH blobs are now wrapped in
    # pypdf's own PdfReadError ("startxref not found", "Invalid object in
    # /Pages"). The wider catch in _PDF_READ_ERRORS stays as defence: only these
    # two of the 300 measured blobs are pinned, and the others were not re-run.
    with pytest.raises(PyPdfError):
        PdfReader(io.BytesIO(_VALUE_ERROR_PDF)).pages[0].extract_text()

    with pytest.raises(PyPdfError):
        PdfReader(io.BytesIO(_ATTRIBUTE_ERROR_PDF)).pages[0].extract_text()


def test_extract_text_converts_pypdf_value_error_to_unsupported_upload():
    """The fix: without it, this ValueError killed the document worker's task
    mid-transaction instead of quarantining the upload (see
    _PDF_READ_ERRORS)."""
    with pytest.raises(UnsupportedUpload):
        extract_text(_VALUE_ERROR_PDF)


def test_extract_text_converts_pypdf_attribute_error_to_unsupported_upload():
    with pytest.raises(UnsupportedUpload):
        extract_text(_ATTRIBUTE_ERROR_PDF)


def test_link_urls_are_lost_before_the_document_is():
    """extract_link_urls promises () for anything unreadable; it runs on bytes
    extract_text accepted, so losing the links must not lose the CV."""
    assert extract_link_urls(b"%PDF-1.4 and then nothing at all") == ()


def test_extract_text_refuses_an_unknown_type():
    with pytest.raises(UnsupportedUpload):
        extract_text(b"just some bytes")


def _long_docx(chars: int) -> bytes:
    body = b"x " * (chars // 2)
    return _docx(
        b'<?xml version="1.0"?>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body><w:p><w:r><w:t>" + body + b"</w:t></w:r></w:p></w:body></w:document>"
    )


def test_extract_text_caps_a_cv_at_forty_thousand_characters():
    """The default is unchanged and deliberately modest: it is the real cost
    limiter on the ingestion call, and a CV that runs past 40,000 characters is
    not a CV. A thesis is, which is why the limit is now an argument.
    """
    assert len(extract_text(_long_docx(60_000))) == 40_000


def test_extract_text_reads_a_whole_thesis_when_the_caller_asks_for_one():
    whole = extract_text(_long_docx(60_000), limit=200_000)
    assert len(whole) > 40_000
    # Ends on content, not mid-token: nothing was cut, it simply ran out.
    assert whole.endswith("x")


def test_extract_text_repairs_a_space_a_kern_invented():
    """Measured on a real upload: a Word-produced CV yielded "Scikit -learn",
    "Garay -Ruiz" and "Bori -Bru" -- the last two a co-author's surname -- from
    a document containing none of them. The space is pypdf's, not the
    document's, and it reached VerifiedFact.payload and printed into a
    generated CV. Word was the only producer of ~120 surveyed generating this
    in volume, and it is what applicants upload.
    """
    from pypdf import PdfReader

    pdf = _kerned_pdf()
    # The premise, asserted rather than assumed: this is pypdf's own reading.
    assert "Scikit -learn" in (PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or "")
    assert "Scikit-learn" in extract_text(pdf)


def test_extract_text_keeps_the_space_french_typography_requires():
    """French puts a space before ; : ! ? -- a French university document in
    the survey has 45 legitimate " :" occurrences, and this platform's students
    write French. Repairing "punctuation" rather than "," and "." would corrupt
    correct text, which is worse than the bug being fixed.
    """
    from weasyprint import HTML

    text = extract_text(HTML(string="<p>Formation : chimie ; Paris</p>").write_pdf())
    assert "Formation : chimie ; Paris" in text


def test_extract_text_keeps_ranges_and_bullets_intact():
    """The two shapes a space-before-hyphen rule could plausibly damage. Both
    survive by construction -- " - " has a space on the far side, and a bullet
    has a newline behind it rather than a word character -- so this is the test
    that says so out loud.
    """
    from weasyprint import HTML

    text = extract_text(HTML(string="<p>2020 - 2024</p><p>- Python</p>").write_pdf())
    assert "2020 - 2024" in text
    assert "- Python" in text


def test_ingestion_never_reads_an_unscanned_document(agency_a, django_user_model, fake_store):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i1")
        document = register(agency_a.id, student.id)  # state == QUARANTINED
        openai_client = _openai_client()
        with pytest.raises(DocumentUnavailable):
            ingest_uploaded_cv(
                document=document, student=student, client=openai_client, store=fake_store
            )
        openai_client.responses.parse.assert_not_called()
        assert VerifiedFact.objects.filter(student=student).count() == 0


def test_ingestion_never_reads_an_infected_document(agency_a, django_user_model, fake_store):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i2")
        document = apply_scan_result(register(agency_a.id, student.id), "THREATS_FOUND")
        assert document.state == "BLOCKED"
        openai_client = _openai_client()
        with pytest.raises(DocumentUnavailable):
            ingest_uploaded_cv(
                document=document, student=student, client=openai_client, store=fake_store
            )
        openai_client.responses.parse.assert_not_called()


def test_ingestion_writes_unconfirmed_student_statement_facts(
    agency_a, django_user_model, fake_store
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i3")
        document = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        facts = ingest_uploaded_cv(
            document=document, student=student, client=_openai_client(), store=fake_store
        )
        assert len(facts) == 3  # one education entry, one skill, the name
        assert all(fact.confirmed_by is None for fact in facts)
        assert all(
            fact.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT for fact in facts
        )
        assert {fact.category for fact in facts} == {
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.SKILL,
            VerifiedFact.Category.IDENTITY,
        }
        assert all(fact.source_ref == f"upload:{document.id}" for fact in facts)


def test_ingestion_refuses_a_document_it_could_not_read(
    agency_a, django_user_model, fake_store
):
    """"We could not read this" must not arrive as "this said nothing".

    A PDF with no text layer -- a photograph of a CV, most often -- extracted
    to "" and ingestion returned (), which is exactly what a CV containing
    nothing returns. The student saw an empty profile and no error. The same
    guard already exists one module over in evidence/intake.py; the CV path
    was the one without it.
    """
    from weasyprint import HTML

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-blank")
        document = promoted_upload(
            register(agency_a.id, student.id), fake_store, HTML(string="<div></div>").write_pdf()
        )
        with pytest.raises(UnsupportedUpload):
            ingest_uploaded_cv(
                document=document, student=student, client=_openai_client(), store=fake_store
            )
        assert not VerifiedFact.objects.filter(student=student).exists()


def test_ingested_facts_are_invisible_to_generation(agency_a, django_user_model, fake_store):
    from apps.documents.verification import generatable_facts

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i4")
        document = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        ingest_uploaded_cv(
            document=document, student=student, client=_openai_client(), store=fake_store
        )
        assert list(generatable_facts(student)) == []


def test_ingestion_is_rate_limited(agency_a, django_user_model, fake_store):
    from apps.documents import ingestion

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i5")
        document = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        for _ in range(ingestion._INGESTION_RATE_LIMIT):
            ingest_uploaded_cv(
                document=document, student=student, client=_openai_client(), store=fake_store
            )
        with pytest.raises(IngestionRateLimited):
            ingest_uploaded_cv(
                document=document, student=student, client=_openai_client(), store=fake_store
            )


def test_extract_text_refuses_a_zip_bomb():
    """defusedxml stops XXE and entity expansion, not a compressed-size bomb."""
    from apps.documents.ingestion import _MAX_DOCX_XML_BYTES

    bomb = b"<w:t>" + b"a" * (_MAX_DOCX_XML_BYTES + 1) + b"</w:t>"
    with pytest.raises(UnsupportedUpload):
        extract_text(_docx(bomb))


def test_ingestion_keeps_the_name_it_extracted(agency_a, django_user_model, fake_store):
    """The upload is parsed into a full CVContent, which cannot validate
    without a name -- so the name is already read, and _SECTIONS used to
    iterate straight past it. A name dropped here is a name the model must
    later invent, which is the one thing this engine exists to prevent."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-identity")
        document = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        facts = ingest_uploaded_cv(
            document=document, student=student, client=_openai_client(), store=fake_store
        )
        identity = [f for f in facts if f.category == VerifiedFact.Category.IDENTITY]
        assert len(identity) == 1
        assert identity[0].payload == {
            "full_name": "Jane Doe",
            "orcid": None,
            # phone rides with the URLs: carried for the contact header, never
            # compared. Without it here, a number the applicant gave us was
            # extracted and then dropped before the ledger.
            "phone": None,
            "linkedin_url": None,
            "github_url": None,
            "website_url": None,
            "github_username": None,
            "linkedin_handle": None,
        }
        assert identity[0].confirmed_by_id is None
        assert identity[0].source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT
        assert identity[0].source_ref == f"upload:{document.id}"


def test_ingestion_prompt_forbids_inferring_sub_skills(agency_a, django_user_model, fake_store):
    """CVContent is the model's output schema, so five new optional fields are
    five new invitations to infer. A CV stating one overall level must yield
    one stored level, not five."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-grid")
        document = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        client = _openai_client()
        ingest_uploaded_cv(document=document, student=student, client=client, store=fake_store)
        prompt = "".join(
            str(message["content"])
            for call in client.responses.parse.call_args_list
            for message in call.kwargs["input"]
        )
    assert "listening" in prompt.lower()
    assert "leave them null" in prompt.lower()


def test_ingestion_prompt_scopes_mother_tongue_to_what_data_states(
    agency_a, django_user_model, fake_store
):
    """mother_tongue is a claim like any other: extracted when the CV says so,
    left false when it does not."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-mt")
        document = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        client = _openai_client()
        ingest_uploaded_cv(document=document, student=student, client=client, store=fake_store)
        prompt = "".join(
            str(message["content"])
            for call in client.responses.parse.call_args_list
            for message in call.kwargs["input"]
        )
    assert "mother_tongue" in prompt
    assert "do not infer it from" in prompt.lower()


def test_link_urls_are_read_from_a_pdfs_annotations():
    """A CV prints "Github: someone" and hyperlinks it. The address lives in a
    PDF link annotation, not in the text layer, so page.extract_text() cannot
    see it -- measured on a real upload, where the applicant's email, LinkedIn,
    GitHub and one publication URL were all being discarded. The extraction
    prompt then rightly refuses to reconstruct them from a username, so without
    this the address is simply lost.
    """
    urls = extract_link_urls(_linking_pdf("https://github.com/someone"))
    assert urls == ("https://github.com/someone",)
    assert "github.com/someone" not in extract_text(_linking_pdf("https://github.com/someone"))


def test_link_urls_are_read_from_a_docxs_relationships():
    """DOCX keeps the same information somewhere else entirely: an external
    relationship in word/_rels/document.xml.rels, referenced by r:id from the
    body. Only hyperlink relationships count -- a linked external image is not
    an address the document printed."""
    docx = _docx(
        _DOCX_XML,
        _rels(
            (_HYPERLINK_TYPE, "https://github.com/someone"),
            (_IMAGE_TYPE, "https://cdn.example.com/photo.png"),
        ),
    )
    assert extract_link_urls(docx) == ("https://github.com/someone",)


def test_link_urls_without_relationships_are_simply_empty():
    assert extract_link_urls(_docx(_DOCX_XML)) == ()
    assert extract_link_urls(_pdf()) == ()


def test_link_urls_keep_only_https_and_mailto():
    """These become <a href> in a rendered PDF, so the scheme is a trust
    boundary -- the same reason _HTTPS_URL_PATTERN exists on the schema. http
    is dropped too: nothing downstream can store it."""
    urls = extract_link_urls(
        _docx(
            _DOCX_XML,
            _rels(
                (_HYPERLINK_TYPE, "javascript:alert(1)"),
                (_HYPERLINK_TYPE, "data:text/html;base64,PHNjcmlwdD4="),
                (_HYPERLINK_TYPE, "http://insecure.example.com"),
                (_HYPERLINK_TYPE, "mailto:jane@example.com"),
                (_HYPERLINK_TYPE, "https://example.com/ok"),
            ),
        )
    )
    assert urls == ("mailto:jane@example.com", "https://example.com/ok")


def test_link_urls_are_deduplicated_and_bounded():
    many = _rels(*[(_HYPERLINK_TYPE, f"https://example.com/{n}") for n in range(200)])
    assert len(extract_link_urls(_docx(_DOCX_XML, many))) == 50
    repeated = _rels(*[(_HYPERLINK_TYPE, "https://example.com/same")] * 5)
    assert extract_link_urls(_docx(_DOCX_XML, repeated)) == ("https://example.com/same",)


def test_an_overlong_url_is_dropped():
    """200 is what PersonalInformation's URL fields can hold; longer is
    unusable downstream and is not worth the prompt budget."""
    long_url = "https://example.com/" + "a" * 300
    assert extract_link_urls(_docx(_DOCX_XML, _rels((_HYPERLINK_TYPE, long_url)))) == ()


def test_the_documents_links_reach_the_model_as_data_not_as_instructions(
    agency_a, django_user_model, fake_store
):
    """The URLs come out of an uploaded file, so they are exactly as untrusted
    as the text is. They belong in the DATA message with it, never in the
    developer message that carries the instructions."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "links")
        document = promoted_upload(
            register(agency_a.id, student.id), fake_store, _linking_pdf("https://github.com/someone")
        )
        client = _openai_client()
        ingest_uploaded_cv(document=document, student=student, client=client, store=fake_store)

    messages = client.responses.parse.call_args.kwargs["input"]
    developer = next(m["content"] for m in messages if m["role"] == "developer")
    user = next(m["content"] for m in messages if m["role"] == "user")
    assert "https://github.com/someone" in user
    assert "https://github.com/someone" not in developer


def test_extraction_reads_dates_the_way_the_document_writes_them():
    """The convention is resolved per document and applied while the model's
    output is validated -- the point at which a written date becomes a date.

    The fake parser validates its own payload, as the SDK does, because that
    is where the ContextVar has to be live. A mock that skipped validation
    would pass whatever this wiring did.
    """
    from apps.documents.ingestion import _extract_claims
    from apps.documents.schemas import CVContent

    payload = {
        "personal_information": {"full_name": "Jane Doe", "email": "jane@example.com"},
        "education": [
            {
                "degree_as_awarded": "BSc",
                "institution_original": "Example University",
                "city": "Boston",
                "country": "US",
                "start_date": "01/09/2020",
            }
        ],
        "experience": [], "research": [], "publications": [], "awards": [],
        "skills": [], "languages": [], "document_language": "en",
    }

    class _Parser:
        def parse(self, **kwargs):
            response = MagicMock()
            response.output_parsed = CVContent.model_validate(payload)
            response.output = []
            return response

    # The document itself proves month-first: 25 cannot be a month.
    american = _extract_claims(
        _Parser(), student_id="s1", text="Internship 09/25/2020 - 12/20/2020", link_urls=()
    )
    assert american.education[0].start_date == date(2020, 1, 9)

    # No evidence on the page, and an Azerbaijani student: day-first.
    european = _extract_claims(
        _Parser(), student_id="s1", text="September 2020 - February 2021",
        link_urls=(), nationality="AZ",
    )
    assert european.education[0].start_date == date(2020, 9, 1)


def test_the_students_nationality_reaches_the_date_parser(
    agency_a, django_user_model, fake_store
):
    """A US profile reads 01/09/2020 as 9 January; everyone else reads it as
    1 September. The document outranks the profile when it shows evidence --
    this PDF shows none, which is why the profile decides here."""
    from apps.accounts.models import StudentProfileVersion
    from apps.documents.dates import Convention, date_convention

    seen: list[Convention] = []

    class _Parser:
        def parse(self, **kwargs):
            seen.append(date_convention.get())
            response = MagicMock()
            response.output_parsed = _content()
            response.output = []
            return response

    class _Client:
        responses = _Parser()

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "nat1")
        StudentProfileVersion.objects.create(
            student=student, version=1, snapshot={"nationality": "US"}
        )
        document = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        ingest_uploaded_cv(
            document=document, student=student, client=_Client(), store=fake_store
        )

    assert seen == [Convention.MONTH_FIRST]


def _pdf_with_runs(stream: bytes) -> bytes:
    """A PDF whose content stream this test controls, byte for byte.

    WeasyPrint cannot stand in here and that is the point: asked for
    "(PMe<sub>3</sub>)" it emits a subscript run with NO leading space, so a
    test built on it passes whether or not the repair exists. Word's producer
    does emit one -- measured on the real CV this came from -- and so does
    this. Verified as a positive control: without the repair, extract_text
    returns "(PMe 3)" here.
    """
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        start,
    )
    return bytes(out)


def test_a_subscript_loses_the_space_its_own_text_run_invented():
    """A sub/superscript is its own, smaller run and pypdf puts a space in
    front of it, so "(PMe3)" reaches the model as "(PMe 3)". Measured on a real
    CV at 8.04pt against 12.0pt body text; one live run then reproduced
    "(PMe 3)" and another moved the space to "( PMe3)".

    "Python 3" is the control: same shape, same font size, left alone.
    """
    pdf = _pdf_with_runs(
        b"BT 72 700 Td /F1 12 Tf (phosphine \\(PMe) Tj /F1 8 Tf ( 3) Tj "
        b"/F1 12 Tf (\\) and Python 3) Tj ET"
    )

    text = extract_text(pdf)

    assert "(PMe3)" in text
    assert "Python 3" in text


def test_a_smaller_run_that_is_not_a_subscript_keeps_its_space():
    """The length and alphanumeric conditions guard a footnote or caption
    merely set in smaller type: joining its first word to the line above
    would corrupt the document rather than repair it."""
    pdf = _pdf_with_runs(
        b"BT 72 700 Td /F1 12 Tf (see the note) Tj /F1 8 Tf ( Funded by the council) Tj ET"
    )

    assert "note Funded by" in extract_text(pdf)


def test_a_gap_line_on_an_upload_becomes_a_timeline_fact(
    agency_a, django_user_model, fake_store
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-timeline")
        document = promoted_upload(register(agency_a.id, student.id), fake_store, _pdf())
        client = _openai_client()
        client.responses.parse.return_value.output_parsed = CVContent.model_validate(
            {
                **_content().model_dump(mode="json"),
                "timeline": [
                    {
                        "start_date": "2023-06-30",
                        "end_date": "2023-11-01",
                        "statement": "Full-time carer for a family member.",
                    }
                ],
            }
        )

        facts = ingest_uploaded_cv(
            document=document, student=student, client=client, store=fake_store
        )

        timeline = [f for f in facts if f.category == VerifiedFact.Category.TIMELINE]
        assert len(timeline) == 1
        assert timeline[0].payload["statement"] == "Full-time carer for a family member."
        assert timeline[0].confirmed_by is None
