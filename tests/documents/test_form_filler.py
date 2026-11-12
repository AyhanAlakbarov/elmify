"""Tests for form_filler: inspecting and filling .docx (FORMTEXT, w:sdt, table cells)
and .pdf (AcroForm vs XFA) templates."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from apps.documents.form_filler import (
    UnsupportedFormFormat,
    fill_docx_repeating_table,
    fill_docx_slots,
    fill_form_template,
    fill_pdf_slots,
    fill_student_form_template,
    inspect_docx_slots,
    inspect_pdf_slots,
)
from apps.documents.ingestion import extract_text
from apps.documents.models import VerifiedFact
from apps.portals.models import Application

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"


def _build_mixed_docx() -> bytes:
    """Build a synthetic .docx containing all three Word form mechanisms:
    1. A legacy FORMTEXT field (`ff:FullName`),
    2. A modern Structured Document Tag content control (`sdt:TargetProgramme`),
    3. A table with a labeled empty cell (`cell:t0_r1_c1`).
    """
    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{_W_NS}">
  <w:body>
    <w:p>
      <w:r>
        <w:fldChar w:fldCharType="begin">
          <w:ffData>
            <w:name w:val="FullName"/>
            <w:statusText w:val="Applicant Full Name"/>
            <w:textInput/>
          </w:ffData>
        </w:fldChar>
      </w:r>
      <w:r><w:instrText xml:space="preserve"> FORMTEXT </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>PLACEHOLDER</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    </w:p>
    <w:sdt>
      <w:sdtPr>
        <w:alias w:val="Target Programme"/>
        <w:tag w:val="TargetProgramme"/>
      </w:sdtPr>
      <w:sdtContent>
        <w:p><w:r><w:t>Click to enter text</w:t></w:r></w:p>
      </w:sdtContent>
    </w:sdt>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Field</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Applicant Answer</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>ECTS Credits Completed</w:t></w:r></w:p></w:tc>
        <w:tc><w:p/></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", xml.encode("utf-8"))
        zf.writestr("[Content_Types].xml", b"<Types/>")
    return buf.getvalue()


def _build_acroform_pdf(*, include_xfa: bool = False) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject("applicant_name"),
            NameObject("/TU"): TextStringObject("Full Name of Applicant"),
            NameObject("/V"): TextStringObject(""),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Rect"): ArrayObject(
                [NumberObject(50), NumberObject(700), NumberObject(300), NumberObject(720)]
            ),
        }
    )
    field_ref = writer._add_object(field)
    page[NameObject("/Annots")] = ArrayObject([field_ref])

    acroform = DictionaryObject(
        {
            NameObject("/Fields"): ArrayObject([field_ref]),
            NameObject("/NeedAppearances"): BooleanObject(True),
        }
    )
    if include_xfa:
        acroform[NameObject("/XFA")] = ArrayObject([])
    writer._root_object[NameObject("/AcroForm")] = writer._add_object(acroform)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_inspect_and_fill_docx_slots_across_formtext_sdt_and_table_cells() -> None:
    raw = _build_mixed_docx()
    slots = inspect_docx_slots(raw)
    assert [(s.slot_id, s.kind, s.label) for s in slots] == [
        ("ff:FullName", "docx_formtext", "Applicant Full Name"),
        ("sdt:TargetProgramme", "docx_sdt", "Target Programme"),
        ("cell:t0_r1_c1", "docx_table_cell", "ECTS Credits Completed — Applicant Answer"),
    ]

    filled = fill_docx_slots(
        raw,
        {
            "ff:FullName": "Orkhan Abdullayev",
            "sdt:TargetProgramme": "M.Sc. Informatics (TUM)",
            "cell:t0_r1_c1": "240 ECTS",
        },
    )
    text = extract_text(filled)
    assert "Orkhan Abdullayev" in text
    assert "M.Sc. Informatics (TUM)" in text
    assert "240 ECTS" in text
    assert "PLACEHOLDER" not in text
    assert "Click to enter text" not in text


def test_docx_rejects_unsafe_zip_paths() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.xml", b"bad")
        zf.writestr("word/document.xml", b"<w:document/>")
    with pytest.raises(ValueError, match="unsafe zip entry path"):
        inspect_docx_slots(buf.getvalue())


def test_inspect_and_fill_pdf_acroform_slots_and_refuse_xfa() -> None:
    pdf_bytes = _build_acroform_pdf()
    inspection = inspect_pdf_slots(pdf_bytes)
    assert not inspection.is_xfa
    assert len(inspection.slots) == 1
    assert inspection.slots[0].slot_id == "applicant_name"
    assert inspection.slots[0].kind == "pdf_text"
    assert inspection.slots[0].label == "Full Name of Applicant"

    filled_pdf = fill_pdf_slots(pdf_bytes, {"applicant_name": "Orkhan Abdullayev"})
    reader = PdfReader(io.BytesIO(filled_pdf))
    fields = reader.get_fields()
    assert fields is not None
    assert fields["applicant_name"].get("/V") == "Orkhan Abdullayev"

    xfa_pdf = _build_acroform_pdf(include_xfa=True)
    xfa_inspection = inspect_pdf_slots(xfa_pdf)
    assert xfa_inspection.is_xfa
    assert xfa_inspection.pdf_kind == "xfa"
    with pytest.raises(UnsupportedFormFormat, match="XFA"):
        fill_pdf_slots(xfa_pdf, {"applicant_name": "Orkhan Abdullayev"})


def test_docx_checkboxes_dropdowns_headers_gridspan_and_vmerge() -> None:
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{_W_NS}" xmlns:w14="{_W14_NS}">
  <w:body>
    <w:p>
      <w:r>
        <w:fldChar w:fldCharType="begin">
          <w:ffData>
            <w:name w:val="NeedsScholarship"/>
            <w:statusText w:val="Apply for scholarship"/>
            <w:checkBox><w:default w:val="0"/></w:checkBox>
          </w:ffData>
        </w:fldChar>
      </w:r>
      <w:r>
        <w:fldChar w:fldCharType="begin">
          <w:ffData>
            <w:name w:val="EnglishLevel"/>
            <w:statusText w:val="CEFR Level"/>
            <w:ddList>
              <w:result w:val="0"/>
              <w:listEntry w:val="B2"/>
              <w:listEntry w:val="C1"/>
              <w:listEntry w:val="C2"/>
            </w:ddList>
          </w:ffData>
        </w:fldChar>
      </w:r>
    </w:p>
    <w:sdt>
      <w:sdtPr>
        <w:alias w:val="Confirm Authenticity"/>
        <w:tag w:val="ConfirmAuth"/>
        <w14:checkbox><w14:checked w14:val="0"/></w14:checkbox>
      </w:sdtPr>
      <w:sdtContent><w:p><w:r><w:t>☐</w:t></w:r></w:p></w:sdtContent>
    </w:sdt>
    <w:sdt>
      <w:sdtPr>
        <w:alias w:val="Degree Track"/>
        <w:tag w:val="DegreeTrack"/>
        <w:dropDownList>
          <w:listItem w:displayText="MSc Artificial Intelligence" w:value="AI"/>
          <w:listItem w:displayText="MSc Data Science" w:value="DS"/>
        </w:dropDownList>
      </w:sdtPr>
      <w:sdtContent><w:p><w:r><w:t>Choose item</w:t></w:r></w:p></w:sdtContent>
    </w:sdt>
    <w:tbl>
      <w:tr>
        <w:tc>
          <w:tcPr><w:gridSpan w:val="2"/></w:tcPr>
          <w:p><w:r><w:t>Module Identification</w:t></w:r></w:p>
        </w:tc>
        <w:tc><w:p><w:r><w:t>ECTS</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc>
          <w:tcPr><w:vMerge w:val="restart"/></w:tcPr>
          <w:p><w:r><w:t>Mathematics</w:t></w:r></w:p>
        </w:tc>
        <w:tc><w:p><w:r><w:t>Linear Algebra</w:t></w:r></w:p></w:tc>
        <w:tc><w:p/></w:tc>
      </w:tr>
      <w:tr>
        <w:tc>
          <w:tcPr><w:vMerge/></w:tcPr>
          <w:p/>
        </w:tc>
        <w:tc><w:p><w:r><w:t>Probability Theory</w:t></w:r></w:p></w:tc>
        <w:tc><w:p/></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>"""
    header_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="{_W_NS}">
  <w:sdt>
    <w:sdtPr><w:tag w:val="HeaderApplicantId"/><w:alias w:val="Applicant ID"/></w:sdtPr>
    <w:sdtContent><w:p><w:r><w:t>ID-000</w:t></w:r></w:p></w:sdtContent>
  </w:sdt>
</w:hdr>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))
        zf.writestr("word/header1.xml", header_xml.encode("utf-8"))
        zf.writestr("[Content_Types].xml", b"<Types/>")
    raw_docx = buf.getvalue()

    slots = inspect_docx_slots(raw_docx)
    slot_summary = [(s.slot_id, s.kind, s.label, s.current_value, s.options) for s in slots]
    assert slot_summary == [
        ("ff:NeedsScholarship", "docx_checkbox", "Apply for scholarship", "false", ()),
        ("ff:EnglishLevel", "docx_dropdown", "CEFR Level", "B2", ("B2", "C1", "C2")),
        ("sdt:ConfirmAuth", "docx_checkbox", "Confirm Authenticity", "false", ()),
        (
            "sdt:DegreeTrack",
            "docx_dropdown",
            "Degree Track",
            "Choose item",
            ("MSc Artificial Intelligence", "MSc Data Science"),
        ),
        ("cell:t0_r1_c2", "docx_table_cell", "Linear Algebra — ECTS", "", ()),
        ("cell:t0_r2_c2", "docx_table_cell", "Probability Theory — ECTS", "", ()),
        ("sdt:HeaderApplicantId", "docx_sdt", "Applicant ID", "ID-000", ()),
    ]

    filled = fill_docx_slots(
        raw_docx,
        {
            "ff:NeedsScholarship": "yes",
            "ff:EnglishLevel": "C1",
            "sdt:ConfirmAuth": "true",
            "sdt:DegreeTrack": "AI",
            "cell:t0_r1_c2": "8",
            "cell:t0_r2_c2": "6",
            "sdt:HeaderApplicantId": "APP-2027-99",
        },
    )
    re_slots = {s.slot_id: s for s in inspect_docx_slots(filled)}
    assert re_slots["ff:NeedsScholarship"].current_value == "true"
    assert re_slots["ff:EnglishLevel"].current_value == "C1"
    assert re_slots["sdt:ConfirmAuth"].current_value == "true"
    assert re_slots["sdt:DegreeTrack"].current_value == "MSc Artificial Intelligence"
    assert re_slots["sdt:HeaderApplicantId"].current_value == "APP-2027-99"

    with pytest.raises(ValueError, match="not in allowed dropdown options"):
        fill_docx_slots(raw_docx, {"ff:EnglishLevel": "A1"})


def test_fill_docx_repeating_table_clones_and_trims_template_rows() -> None:
    raw = _build_mixed_docx()
    expanded = fill_docx_repeating_table(
        raw,
        table_index=0,
        header_rows=1,
        rows=[
            ("Algorithms and Data Structures", "8 ECTS"),
            ("Operating Systems", "6 ECTS"),
            ("Machine Learning", "6 ECTS"),
        ],
    )
    text = extract_text(expanded)
    assert "Algorithms and Data Structures" in text
    assert "Operating Systems" in text
    assert "Machine Learning" in text
    assert "ECTS Credits Completed" not in text


def test_pdf_checkbox_custom_state_dropdown_and_scanned_detection() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    cb_field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Btn"),
            NameObject("/T"): TextStringObject("confirm_terms"),
            NameObject("/TU"): TextStringObject("Confirm Terms"),
            NameObject("/V"): NameObject("/Off"),
            NameObject("/AS"): NameObject("/Off"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Rect"): ArrayObject(
                [NumberObject(50), NumberObject(650), NumberObject(70), NumberObject(670)]
            ),
            NameObject("/AP"): DictionaryObject(
                {
                    NameObject("/N"): DictionaryObject(
                        {
                            NameObject("/On"): DictionaryObject(),
                            NameObject("/Off"): DictionaryObject(),
                        }
                    )
                }
            ),
        }
    )
    ch_field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Ch"),
            NameObject("/T"): TextStringObject("intake_semester"),
            NameObject("/TU"): TextStringObject("Intake Semester"),
            NameObject("/V"): TextStringObject("Winter"),
            NameObject("/Opt"): ArrayObject(
                [TextStringObject("Winter"), TextStringObject("Summer")]
            ),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Rect"): ArrayObject(
                [NumberObject(100), NumberObject(650), NumberObject(250), NumberObject(670)]
            ),
        }
    )
    cb_ref = writer._add_object(cb_field)
    ch_ref = writer._add_object(ch_field)
    page[NameObject("/Annots")] = ArrayObject([cb_ref, ch_ref])
    writer._root_object[NameObject("/AcroForm")] = writer._add_object(
        DictionaryObject({NameObject("/Fields"): ArrayObject([cb_ref, ch_ref])})
    )
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    inspection = inspect_pdf_slots(pdf_bytes)
    assert inspection.pdf_kind == "acroform"
    assert [(s.slot_id, s.kind, s.options) for s in inspection.slots] == [
        ("confirm_terms", "pdf_checkbox", ("/On", "/Off")),
        ("intake_semester", "pdf_dropdown", ("Winter", "Summer")),
    ]

    filled = fill_pdf_slots(
        pdf_bytes,
        {"confirm_terms": "yes", "intake_semester": "Summer"},
    )
    re_reader = PdfReader(io.BytesIO(filled))
    fields = re_reader.get_fields()
    assert fields is not None
    assert str(fields["confirm_terms"].get("/V")) == "/On"
    assert str(fields["intake_semester"].get("/V")) == "Summer"

    with pytest.raises(ValueError, match="not in allowed dropdown options"):
        fill_pdf_slots(pdf_bytes, {"intake_semester": "Spring"})

    # Blank non-AcroForm PDF is classified as scanned_image
    blank_writer = PdfWriter()
    blank_writer.add_blank_page(width=612, height=792)
    blank_buf = io.BytesIO()
    blank_writer.write(blank_buf)
    blank_insp = inspect_pdf_slots(blank_buf.getvalue())
    assert blank_insp.pdf_kind == "scanned_image"
    with pytest.raises(UnsupportedFormFormat, match="scanned_image"):
        fill_pdf_slots(blank_buf.getvalue(), {})


def test_fill_form_template_end_to_end_docx_pdf_and_fallback() -> None:
    # 1. End-to-end .docx filling by human label with normalize_text hygiene
    raw_docx = _build_mixed_docx()
    docx_res = fill_form_template(
        raw_docx,
        {
            "Applicant Full Name": "Aysel\u00a0Mammadova\u200b",
            "Target Programme": "MSc Computer Science",
            "ECTS Credits Completed": "180 ECTS",
        },
    )
    assert docx_res.mode == "docx_filled"
    assert docx_res.filled_bytes is not None
    assert len(docx_res.field_mapped) == 3
    docx_text = extract_text(docx_res.filled_bytes)
    assert "\u00a0" not in docx_text
    assert "\u200b" not in docx_text
    assert "Aysel Mammadova" in docx_text

    # 2. End-to-end AcroForm .pdf filling by human label with metadata scrubbing
    pdf_bytes = _build_acroform_pdf()
    pdf_res = fill_form_template(
        pdf_bytes,
        {"Full Name of Applicant": "Aysel\u00a0Mammadova"},
    )
    assert pdf_res.mode == "pdf_filled"
    assert pdf_res.filled_bytes is not None
    re_reader = PdfReader(io.BytesIO(pdf_res.filled_bytes))
    fields = re_reader.get_fields()
    assert fields is not None
    assert str(fields["applicant_name"].get("/V")) == "Aysel Mammadova"

    # 3. Automatic field_mapped_fallback for XFA / flat / scanned PDFs
    xfa_bytes = _build_acroform_pdf(include_xfa=True)
    xfa_res = fill_form_template(
        xfa_bytes,
        {"Full Name of Applicant": "Aysel Mammadova"},
    )
    assert xfa_res.mode == "field_mapped_fallback"
    assert xfa_res.filled_bytes is None
    assert "XFA" in xfa_res.fallback_reason
    assert xfa_res.field_mapped == {"Full Name of Applicant": "Aysel Mammadova"}


def test_real_funder_templates_aa_and_sisgp_round_trip() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    aa_path = repo_root / ".superpowers" / "sdd" / "docx-editing-history" / "aa.docx"
    sisgp_path = repo_root / ".superpowers" / "sdd" / "docx-editing-history" / "sisgp.docx"

    if aa_path.exists():
        aa_bytes = aa_path.read_bytes()
        aa_slots = inspect_docx_slots(aa_bytes)
        assert len(aa_slots) == 112
        # Every slot_id is disambiguated despite copy-pasted Text12/Text172 in XML
        assert len({s.slot_id for s in aa_slots}) == len(aa_slots)
        # Contextual table labels are extracted even when w:statusText is empty
        slot_by_id = {s.slot_id: s for s in aa_slots}
        assert "Full name" in slot_by_id["ff:Text12"].label
        assert "Date of birth" in slot_by_id["ff:Text12_2"].label

        aa_res = fill_form_template(
            aa_bytes,
            {
                "ff:Text12": "Aysel Mammadova",
                "ff:Text12_2": "14/05/2003",
                "ff:Text12_3": "Female",
            },
        )
        assert aa_res.filled_bytes is not None
        re_aa = {s.slot_id: s for s in inspect_docx_slots(aa_res.filled_bytes)}
        assert re_aa["ff:Text12"].current_value == "Aysel Mammadova"
        assert re_aa["ff:Text12_2"].current_value == "14/05/2003"
        assert re_aa["ff:Text12_3"].current_value == "Female"
        # Neighboring duplicate-named Text12 slots remain untouched at their default
        assert re_aa["ff:Text12_4"].current_value == slot_by_id["ff:Text12_4"].current_value

    if sisgp_path.exists():
        sisgp_bytes = sisgp_path.read_bytes()
        sisgp_slots = inspect_docx_slots(sisgp_bytes)
        assert len(sisgp_slots) == 47
        sisgp_by_id = {s.slot_id: s for s in sisgp_slots}
        assert sisgp_by_id["sdt:0"].kind == "docx_dropdown"
        assert sisgp_by_id["sdt:0"].options == ("Choose one", "Female", "Male")

        sisgp_res = fill_form_template(
            sisgp_bytes,
            {
                "sdt:0": "Female",
                "cell:t0_r0_c1": "Aysel, Mammadova",
                "cell:t2_r0_c1": "Research Assistant - State Oil Company (SOCAR)",
            },
        )
        assert sisgp_res.filled_bytes is not None
        re_sisgp = {s.slot_id: s for s in inspect_docx_slots(sisgp_res.filled_bytes)}
        assert re_sisgp["sdt:0"].current_value == "Female"
        sisgp_text = extract_text(sisgp_res.filled_bytes)
        assert "Aysel, Mammadova" in sisgp_text
        assert "Research Assistant - State Oil Company (SOCAR)" in sisgp_text


def test_multilingual_docx_labels_placeholders_and_checkbox_values() -> None:
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{_W_NS}" xmlns:w14="{_W14_NS}">
  <w:body>
    <w:sdt>
      <w:sdtPr>
        <w:alias w:val="Prüfungsfach"/>
        <w:tag w:val="SubjectField"/>
      </w:sdtPr>
      <w:sdtContent>
        <w:p><w:r><w:t>Klicken oder tippen Sie hier, um Text einzugeben.</w:t></w:r></w:p>
      </w:sdtContent>
    </w:sdt>
    <w:sdt>
      <w:sdtPr>
        <w:alias w:val="Stipendium beantragen"/>
        <w:tag w:val="ApplyScholarship"/>
        <w14:checkbox><w14:checked w14:val="0"/></w14:checkbox>
      </w:sdtPr>
      <w:sdtContent><w:p><w:r><w:t>☐</w:t></w:r></w:p></w:sdtContent>
    </w:sdt>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Prénom de l’étudiant</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Cliquez ou appuyez ici pour entrer du texte.</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))
        zf.writestr("[Content_Types].xml", b"<Types/>")
    raw_docx = buf.getvalue()

    res = fill_form_template(
        raw_docx,
        {
            "Prufungsfach": "Theoretische Informatik",
            "Stipendium beantragen": "ja",
            "Prénom de l’étudiant": "Chloé Laurent",
        },
    )
    assert res.mode == "docx_filled"
    assert res.filled_bytes is not None
    re_slots = {s.slot_id: s for s in inspect_docx_slots(res.filled_bytes)}
    assert re_slots["sdt:SubjectField"].current_value == "Theoretische Informatik"
    assert re_slots["sdt:ApplyScholarship"].current_value == "true"
    text = extract_text(res.filled_bytes)
    assert "Theoretische Informatik" in text
    assert "Chloé Laurent" in text
    assert "Cliquez ou appuyez ici" not in text


@pytest.mark.django_db
def test_fill_application_form_portal_view_and_tenant_isolation(
    client,
    agency_a,
    agency_b,
    domain_a,
    membership_a,
    membership_b,
    user_a,
) -> None:
    from uuid import uuid4

    from apps.tenancy.context import tenant_scope

    now = timezone.now()
    with tenant_scope(agency_a.id):
        app_a = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            name="MSc Informatics",
        )
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={
                "given_names": "Aysel",
                "surname": "Mammadova",
                "date_of_birth": "2002-05-14",
                "sex": "F",
                "citizenship": "Azerbaijan",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:passport",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.EDUCATION,
            payload={
                "institution_english": "ETH Zurich",
                "degree_english": "BSc Computer Science",
                "total_credits": "180 ECTS",
                "grade_native": "5.6/6.0",
                "courses": [
                    {"title": "Linear Algebra", "credits": "8", "grade": "5.75"},
                ],
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="transcript",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={
                "employer": "DeepMind",
                "title": "Research Intern",
                "bullets": ["Trained sparse mixture-of-experts transformers."],
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="cv",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )

    with tenant_scope(agency_b.id):
        app_b = Application.objects.create(
            tenant=agency_b,
            student=membership_b,
            program_id=uuid4(),
            name="MSc Robotics",
        )

    client.force_login(user_a)
    url = reverse("student-document-fill-form")

    # 1. End-to-end .docx form upload -> auto-filled from VerifiedFact rows & Application
    raw_docx = _build_mixed_docx()
    docx_upload = SimpleUploadedFile(
        "daad_module_sheet.docx",
        raw_docx,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    resp = client.post(
        url,
        {"template_file": docx_upload, "application_id": str(app_a.id)},
        HTTP_HOST=domain_a.host,
    )
    assert resp.status_code == 200
    assert resp["X-Form-Fill-Mode"] == "docx_filled"
    assert 'filename="filled-daad_module_sheet.docx"' in resp["Content-Disposition"]
    filled_text = extract_text(resp.content)
    assert "Aysel Mammadova" in filled_text
    assert "MSc Informatics" in filled_text
    assert "180 ECTS" in filled_text

    # 2. End-to-end XFA PDF upload -> degrades to field_mapped_fallback download
    xfa_pdf = _build_acroform_pdf(include_xfa=True)
    xfa_upload = SimpleUploadedFile(
        "daad_xfa.pdf",
        xfa_pdf,
        content_type="application/pdf",
    )
    xfa_resp = client.post(url, {"template_file": xfa_upload}, HTTP_HOST=domain_a.host)
    assert xfa_resp.status_code == 200
    assert xfa_resp["X-Form-Fill-Mode"] == "field_mapped_fallback"
    assert b"Full Name of Applicant: Aysel Mammadova" in xfa_resp.content

    # 3. Tenant & student isolation: Student A cannot reference Tenant B's Application
    cross_tenant_upload = SimpleUploadedFile(
        "daad_module_sheet.docx",
        raw_docx,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    cross_resp = client.post(
        url,
        {"template_file": cross_tenant_upload, "application_id": str(app_b.id)},
        HTTP_HOST=domain_a.host,
    )
    assert cross_resp.status_code == 404

    # 4. Auto-mapping VerifiedFact records directly onto real aa.docx and sisgp.docx templates
    repo_root = Path(__file__).resolve().parents[2]
    sisgp_path = repo_root / ".superpowers" / "sdd" / "docx-editing-history" / "sisgp.docx"
    if sisgp_path.exists():
        with tenant_scope(agency_a.id):
            facts_a = list(VerifiedFact.objects.filter(student=membership_a))
        sisgp_auto = fill_student_form_template(
            sisgp_path.read_bytes(),
            facts=facts_a,
            target_programme="MSc Informatics",
        )
        assert sisgp_auto.mode == "docx_filled"
        assert sisgp_auto.filled_bytes is not None
        re_sisgp = {s.slot_id: s for s in inspect_docx_slots(sisgp_auto.filled_bytes)}
        assert re_sisgp["sdt:0"].current_value == "Female"
        sisgp_auto_text = extract_text(sisgp_auto.filled_bytes)
        assert "Aysel Mammadova" in sisgp_auto_text
        assert "Research Intern" in sisgp_auto_text
        assert "DeepMind" in sisgp_auto_text


@pytest.mark.django_db
def test_fill_application_form_shares_passport_identity_phone_ects_and_profile_fallback(
    client,
    agency_a,
    domain_a,
    user_a,
    membership_a,
) -> None:
    """Ensure active picked ID_DOCUMENT (excluded by generatable_facts), IDENTITY phone/given_name,
    EDUCATION ects_credits, academic_email, and StudentProfileVersion snapshot fallbacks all reach
    fill_application_form."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.urls import reverse
    from django.utils import timezone

    from apps.accounts.models import StudentProfileVersion
    from apps.documents.models import VerifiedFact
    from apps.tenancy.context import tenant_scope

    now = timezone.now()
    with tenant_scope(agency_a.id):
        membership_a.academic_email = "a.mammadova@ada.edu.az"
        membership_a.save(update_fields=["academic_email"])

        StudentProfileVersion.objects.create(
            tenant=agency_a,
            student=membership_a,
            version=1,
            schema_version=3,
            snapshot={
                "nationality": ["Azerbaijani"],
                "country_of_residence": "Azerbaijan",
                "date_of_birth": "2002-05-14",
            },
        )
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.ID_DOCUMENT,
            payload={
                "document_type": "passport",
                "number": "C99887766",
                "issuing_country": "AZ",
                "issue_date": "2023-01-10",
                "expiry_date": "2033-01-10",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:11111111-1111-1111-1111-111111111111",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={
                "given_name": "Aysel",
                "surname": "Mammadova",
                "phone": "+994501112233",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="gap_interview",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.EDUCATION,
            payload={
                "institution_english": "ADA University",
                "degree_english": "BSc Computer Science",
                "ects_credits": "240 ECTS",
                "grade_native": "3.92/4.00",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="transcript",
            confirmed_by=membership_a,
            confirmed_at=now,
            created_by=membership_a,
        )

    rows_xml = "".join(
        f"<w:tr><w:tc><w:p><w:r><w:t>{lbl}</w:t></w:r></w:p></w:tc><w:tc><w:p/></w:tc></w:tr>"
        for lbl in (
            "Passport Number",
            "Phone Number",
            "Email Address",
            "Nationality",
            "Date of Birth",
            "ECTS Credits",
        )
    )
    xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}"><w:body><w:tbl>{rows_xml}</w:tbl></w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", xml.encode("utf-8"))
        zf.writestr("[Content_Types].xml", b"<Types/>")

    client.force_login(user_a)
    resp = client.post(
        reverse("student-document-fill-form"),
        {
            "template_file": SimpleUploadedFile(
                "check_form.docx",
                buf.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        HTTP_HOST=domain_a.host,
    )
    assert resp.status_code == 200
    filled_text = extract_text(resp.content)
    assert "C99887766" in filled_text
    assert "+994501112233" in filled_text
    assert "a.mammadova@ada.edu.az" in filled_text
    assert "Azerbaijani" in filled_text
    assert "2002-05-14" in filled_text
    assert "240 ECTS" in filled_text


def test_map_student_facts_to_slots_prefers_test_backed_language_and_keeps_location_distinct():
    from types import SimpleNamespace

    from apps.documents.form_filler import FormSlot, map_student_facts_to_slots

    slots = [
        FormSlot(slot_id="s_city", label="Current Address", kind="docx_table_cell"),
        FormSlot(slot_id="s_res", label="Country of Residence", kind="docx_table_cell"),
        FormSlot(slot_id="s_mt", label="Mother Tongue", kind="docx_table_cell"),
        FormSlot(slot_id="s_cefr", label="CEFR Level", kind="docx_table_cell"),
        FormSlot(slot_id="s_de", label="German Level", kind="docx_table_cell"),
        FormSlot(slot_id="s_score", label="IELTS Score", kind="docx_table_cell"),
        FormSlot(slot_id="s_ref", label="Referee Name", kind="docx_table_cell"),
        FormSlot(slot_id="s_ref_mail", label="Referee Email", kind="docx_table_cell"),
        FormSlot(slot_id="s_awards", label="Honours and Awards", kind="docx_table_cell"),
        FormSlot(slot_id="s_pubs", label="List of Publications", kind="docx_table_cell"),
        FormSlot(
            slot_id="s_course",
            label="Organic Chemistry I — ECTS Credits",
            kind="docx_table_cell",
        ),
    ]
    facts = [
        SimpleNamespace(
            category="IDENTITY",
            payload={"full_name": "Aysel Mammadova", "location": "Baku, Azerbaijan"},
        ),
        SimpleNamespace(
            category="LANGUAGE",
            payload={"language": "Azerbaijani", "mother_tongue": True, "cefr_level": "C2"},
        ),
        SimpleNamespace(
            category="LANGUAGE",
            payload={
                "language": "English",
                "mother_tongue": False,
                "cefr_level": "C1",
                "test_name": "IELTS",
                "test_score": "7.5",
            },
        ),
        SimpleNamespace(
            category="LANGUAGE",
            payload={"language": "German", "mother_tongue": False, "cefr_level": "B2"},
        ),
        SimpleNamespace(
            category="EDUCATION",
            payload={
                "institution_english": "Baku State University",
                "degree_english": "BSc Chemistry",
                "courses": [{"title": "Organic Chemistry I", "ects": "6.00", "grade": "95"}],
            },
        ),
        SimpleNamespace(
            category="REFERENCE",
            payload={
                "name": "Elena Petrova",
                "position": "Prof. Dr.",
                "institution": "ETH Zurich",
                "email": "petrova@ethz.ch",
            },
        ),
        SimpleNamespace(
            category="AWARD",
            payload={"title": "Presidential Scholarship"},
        ),
        SimpleNamespace(
            category="PUBLICATION",
            payload={"title": "Catalytic Asymmetric Synthesis"},
        ),
    ]
    mapped = map_student_facts_to_slots(
        slots,
        facts=facts,
        passport_details={"country_of_residence": "AZ"},
    )
    assert mapped["s_city"] == "Baku, Azerbaijan"
    assert mapped["s_res"] == "AZ"
    assert mapped["s_mt"] == "Azerbaijani"
    assert mapped["s_cefr"] == "C1"
    assert mapped["s_de"] == "B2"
    assert mapped["s_score"] == "7.5"
    assert mapped["s_ref"] == "Prof. Dr. Elena Petrova"
    assert mapped["s_ref_mail"] == "petrova@ethz.ch"
    assert mapped["s_awards"] == "Presidential Scholarship"
    assert mapped["s_pubs"] == "Catalytic Asymmetric Synthesis"
    assert mapped["s_course"] == "6.00"


def test_corrupt_docx_and_pdf_raise_value_error_not_500() -> None:
    with pytest.raises(ValueError, match="not a valid .docx archive"):
        inspect_docx_slots(b"PK\x03\x04truncated-corrupt-zip-stream")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", b"<w:document><unclosed>")
    with pytest.raises(ValueError, match="corrupt or unsafe XML"):
        inspect_docx_slots(buf.getvalue())

    with pytest.raises(ValueError, match="corrupt or unreadable PDF"):
        inspect_pdf_slots(b"%PDF-1.4\ntruncated-corrupt-pdf")

