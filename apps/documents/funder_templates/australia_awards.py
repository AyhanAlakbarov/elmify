"""Australia Awards DFAT CV template (R-065, R-081, R-083).

Supports both mechanisms required by the DFAT template:
1. Populating legacy Word ``FORMTEXT`` form fields inside ``word/document.xml``
   of the official DFAT ``.docx`` template (``fill_australia_awards_docx``),
   including split ``DD`` / ``MM`` / ``YYYY`` date controls and computed
   ``total_duration_months``.
2. Rendering a matching tabular PDF + ``field_mapped`` ``RenderedArtifact``
   (``render_australia_awards``) for preview and worker release pipelines.
"""

from __future__ import annotations

import copy
import io
import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, tostring  # nosec B405

from django.template.loader import render_to_string

from apps.documents.entry_selection import select_best_entries
from apps.documents.render import RenderedArtifact, hygienic_content, render_html_to_artifact
from apps.documents.schemas import CVContent, EducationEntry, ExperienceEntry
from apps.documents.templatetags.cv_countries import country_name

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _W_NS}
_W_VAL = f"{{{_W_NS}}}val"
_W_FLD_CHAR_TYPE = f"{{{_W_NS}}}fldCharType"

_DEFAULT_DOCX_PATH = (
    Path(__file__).resolve().parents[3]
    / ".superpowers"
    / "sdd"
    / "docx-editing-history"
    / "aa.docx"
)


def split_dmy(value: date | None) -> tuple[str, str, str]:
    """Return ``(DD, MM, YYYY)`` strings for Word's three-part date controls."""
    if value is None:
        return ("", "", "")
    return (f"{value.day:02d}", f"{value.month:02d}", f"{value.year:04d}")


def format_dmy(value: date | None) -> str:
    """Format a date as ``DD/MM/YYYY`` per the DFAT template."""
    if value is None:
        return ""
    return f"{value.day:02d}/{value.month:02d}/{value.year:04d}"


def total_duration_months(
    start_date: date | None,
    end_date: date | None,
    *,
    today: date | None = None,
) -> int | None:
    """Compute the DFAT 'Total duration (in months)' column from start and end dates."""
    if start_date is None:
        return None
    effective_end = end_date or today or date.today()
    if effective_end < start_date:
        return 0
    months = (effective_end.year - start_date.year) * 12 + (
        effective_end.month - start_date.month
    )
    if effective_end.day >= start_date.day:
        months += 1
    return max(1, months)


def _duty_station(entry: ExperienceEntry) -> str:
    parts = [p for p in (entry.city, country_name(entry.country) if entry.country else "") if p]
    return ", ".join(parts)


def _institution_name_and_address(entry: EducationEntry) -> str:
    name = entry.institution_original
    if entry.institution_english and entry.institution_english != entry.institution_original:
        name = f"{name} ({entry.institution_english})"
    parts = [
        p
        for p in (name, entry.city, country_name(entry.country) if entry.country else "")
        if p
    ]
    return ", ".join(parts)


def _degree_label(entry: EducationEntry) -> str:
    if entry.degree_english and entry.degree_english != entry.degree_as_awarded:
        return f"{entry.degree_as_awarded} ({entry.degree_english})"
    return entry.degree_as_awarded


def _grade_label(entry: EducationEntry) -> str:
    if not entry.grade_native:
        return ""
    text = entry.grade_native
    if entry.grade_scale and entry.grade_scale not in text:
        text = f"{text} ({entry.grade_scale})"
    if entry.grade_conversion:
        text = f"{text} ≈ {entry.grade_conversion}"
    return text


def australia_awards_fields(
    content: CVContent, *, today: date | None = None
) -> dict[str, Any]:
    """Build the structured dictionary for all six DFAT Australia Awards sections."""
    clean = hygienic_content(content)
    ref_today = today or date.today()

    paid = select_best_entries(
        tuple(entry for entry in clean.experience if not entry.unpaid),
        limit=len(clean.experience),
        key=lambda entry: entry.start_date,
    )
    unpaid = select_best_entries(
        tuple(entry for entry in clean.experience if entry.unpaid),
        limit=len(clean.experience),
        key=lambda entry: entry.start_date,
    )
    education = select_best_entries(
        clean.education,
        limit=len(clean.education),
        key=lambda entry: entry.start_date,
    )

    work_rows = [
        {
            "organisation_name": entry.employer,
            "designation": entry.title,
            "duty_station": _duty_station(entry),
            "start_date": format_dmy(entry.start_date),
            "start_dmy": split_dmy(entry.start_date),
            "end_date": (
                format_dmy(entry.end_date)
                if entry.end_date
                else ("Present" if entry.start_date else "")
            ),
            "end_dmy": split_dmy(entry.end_date),
            "total_duration_months": total_duration_months(
                entry.start_date, entry.end_date, today=ref_today
            ),
            "responsibilities": "; ".join(entry.bullets),
        }
        for entry in paid
    ]

    academic_rows = [
        {
            "institution_name_and_address": _institution_name_and_address(entry),
            "degree_obtained": _degree_label(entry),
            "start_date": format_dmy(entry.start_date),
            "start_dmy": split_dmy(entry.start_date),
            "end_date": format_dmy(entry.end_date),
            "end_dmy": split_dmy(entry.end_date),
            "final_grade": _grade_label(entry),
            "medium_of_instruction": entry.medium_of_instruction or "",
            "institution_type": "",
        }
        for entry in education
    ]

    awards_lines = [
        ", ".join(
            p
            for p in (
                item.title,
                item.awarding_body,
                format_dmy(item.date) if item.date else "",
                item.detail,
            )
            if p
        )
        for item in clean.awards
    ] + [
        ", ".join(
            p
            for p in (
                cert.title,
                cert.issuer,
                format_dmy(cert.date) if cert.date else "",
            )
            if p
        )
        for cert in clean.certifications
    ]

    research_lines: list[str] = []
    for res in clean.research:
        parts = [
            res.thesis_title,
            res.institution,
            f"Supervisor: {res.supervisor}" if res.supervisor else "",
            res.methods,
            res.outcomes,
        ]
        research_lines.append(" — ".join(p for p in parts if p))
    for pub in clean.publications:
        authors = ", ".join(pub.authors)
        cite_parts = [
            authors,
            pub.title,
            pub.venue,
            str(pub.year) if pub.year else "",
        ]
        research_lines.append(". ".join(p for p in cite_parts if p))

    network_lines = [
        " — ".join(
            p
            for p in (
                f"{entry.title}, {entry.employer}",
                _duty_station(entry),
                "; ".join(entry.bullets),
            )
            if p
        )
        for entry in unpaid
    ]

    personal = clean.personal_information
    return {
        "personal_details": {
            "full_name": personal.full_name,
            "date_of_birth": format_dmy(personal.date_of_birth),
            "mailing_address": "",
            "residential_address": "",
            "permanent_address": "",
            "mobile_phone": personal.phone or "",
            "email": personal.email,
        },
        "work_experience": work_rows,
        "academic_record": academic_rows,
        "awards": awards_lines,
        "research_and_publications": research_lines,
        "networks_and_memberships": network_lines,
    }


def _set_formtext_values_in_container(container: Element, values: list[str]) -> None:
    """Populate sequential ``FORMTEXT`` fields inside ``container`` in document order.

    Updates both ``w:ffData/w:textInput/w:default/@w:val`` and the displayed
    ``w:t`` run between ``fldCharType="separate"`` and ``fldCharType="end"``.
    """
    field_index = -1
    in_result = False
    wrote_in_current = False

    for elem in container.iter():
        if elem.tag == f"{{{_W_NS}}}fldChar":
            kind = elem.attrib.get(_W_FLD_CHAR_TYPE)
            if kind == "begin":
                ff_data = elem.find("w:ffData", _NS)
                if ff_data is not None and ff_data.find("w:textInput", _NS) is not None:
                    field_index += 1
                    target_val = values[field_index] if field_index < len(values) else ""
                    default_el = ff_data.find("w:textInput/w:default", _NS)
                    if default_el is not None:
                        default_el.attrib[_W_VAL] = target_val
                    in_result = False
                    wrote_in_current = False
            elif kind == "separate" and field_index >= 0:
                in_result = True
            elif kind == "end":
                in_result = False
        elif in_result and elem.tag == f"{{{_W_NS}}}t":
            target_val = values[field_index] if 0 <= field_index < len(values) else ""
            if not wrote_in_current:
                elem.text = target_val
                wrote_in_current = True
            else:
                elem.text = ""


def _ensure_table_rows(table: Element, needed_data_rows: int) -> list[Element]:
    """Ensure ``table`` has at least ``needed_data_rows`` rows after the header row."""
    rows = table.findall("./w:tr", _NS)
    data_rows = rows[1:]
    if not data_rows:
        return []
    while len(data_rows) < needed_data_rows:
        cloned = copy.deepcopy(data_rows[-1])
        table.append(cloned)
        data_rows.append(cloned)
    return data_rows


def fill_australia_awards_docx(
    content: CVContent,
    template_bytes: bytes | None = None,
    *,
    today: date | None = None,
) -> bytes:
    """Populate the Word ``FORMTEXT`` fields of the DFAT Australia Awards DOCX template."""
    if template_bytes is None:
        if not _DEFAULT_DOCX_PATH.is_file():
            raise FileNotFoundError(
                f"Australia Awards DOCX template not found at {_DEFAULT_DOCX_PATH}"
            )
        template_bytes = _DEFAULT_DOCX_PATH.read_bytes()

    from apps.documents.form_filler.docx import (
        _MAX_DOCX_UNCOMPRESSED_BYTES,
        _parse_docx_xml,
        _read_zip_member,
        _validate_docx_archive,
    )

    fields = australia_awards_fields(content, today=today)
    try:
        zin_ctx = zipfile.ZipFile(io.BytesIO(template_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise ValueError("not a valid Australia Awards .docx archive") from exc
    with zin_ctx as zin:
        _validate_docx_archive(zin)
        remaining = _MAX_DOCX_UNCOMPRESSED_BYTES
        doc_xml = _read_zip_member(zin, "word/document.xml", max_bytes=remaining)
        remaining -= len(doc_xml)
        other_entries: dict[str, bytes] = {}
        for name in zin.namelist():
            if name != "word/document.xml":
                raw_other = _read_zip_member(zin, name, max_bytes=remaining)
                remaining -= len(raw_other)
                other_entries[name] = raw_other

    root = _parse_docx_xml(doc_xml)
    tables = root.findall(".//w:tbl", _NS)
    if len(tables) < 3:
        raise ValueError("Australia Awards DOCX template is missing expected tables")

    # Table 0: Personal Details (7 data rows)
    personal = fields["personal_details"]
    personal_values = [
        personal["full_name"],
        personal["date_of_birth"],
        personal["mailing_address"],
        personal["residential_address"],
        personal["permanent_address"],
        personal["mobile_phone"],
        personal["email"],
    ]
    for row_el, val in zip(tables[0].findall("./w:tr", _NS)[1:], personal_values, strict=False):
        _set_formtext_values_in_container(row_el, [val])

    # Table 1: Work Experience
    work_rows_data: list[dict[str, Any]] = fields["work_experience"]
    work_row_els = _ensure_table_rows(tables[1], len(work_rows_data))
    for idx, row_el in enumerate(work_row_els):
        if idx < len(work_rows_data):
            w = work_rows_data[idx]
            s_dd, s_mm, s_yyyy = w["start_dmy"]
            e_dd, e_mm, e_yyyy = w["end_dmy"]
            duration_str = (
                str(w["total_duration_months"])
                if w["total_duration_months"] is not None
                else ""
            )
            row_vals = [
                w["organisation_name"],
                w["designation"],
                w["duty_station"],
                s_dd,
                s_mm,
                s_yyyy,
                e_dd,
                e_mm,
                e_yyyy,
                duration_str,
                w["responsibilities"],
            ]
        else:
            row_vals = [""] * 11
        _set_formtext_values_in_container(row_el, row_vals)

    # Table 2: Academic Record
    acad_rows_data: list[dict[str, Any]] = fields["academic_record"]
    acad_row_els = _ensure_table_rows(tables[2], len(acad_rows_data))
    for idx, row_el in enumerate(acad_row_els):
        if idx < len(acad_rows_data):
            a = acad_rows_data[idx]
            s_dd, s_mm, s_yyyy = a["start_dmy"]
            e_dd, e_mm, e_yyyy = a["end_dmy"]
            row_vals = [
                a["institution_name_and_address"],
                a["degree_obtained"],
                s_dd,
                s_mm,
                s_yyyy,
                e_dd,
                e_mm,
                e_yyyy,
                a["final_grade"],
                a["medium_of_instruction"],
                a["institution_type"],
            ]
        else:
            row_vals = [""] * 11
        _set_formtext_values_in_container(row_el, row_vals)

    # Trailing prose FORMTEXT paragraphs after Table 2 (2 paragraphs per section:
    # Awards, Research & Publications, Networks & Memberships).
    body = root.find("w:body", _NS)
    if body is not None:
        after_acad = False
        prose_form_paras: list[Element] = []
        for child in body:
            if child is tables[2]:
                after_acad = True
                continue
            if after_acad and child.tag == f"{{{_W_NS}}}p":
                if child.find(".//w:ffData", _NS) is not None:
                    prose_form_paras.append(child)
        prose_groups = [
            fields["awards"],
            fields["research_and_publications"],
            fields["networks_and_memberships"],
        ]
        for group_idx, lines in enumerate(prose_groups):
            first_para_idx = group_idx * 2
            second_para_idx = first_para_idx + 1
            if first_para_idx < len(prose_form_paras):
                first_text = lines[0] if lines else ""
                _set_formtext_values_in_container(prose_form_paras[first_para_idx], [first_text])
            if second_para_idx < len(prose_form_paras):
                rest_text = "; ".join(lines[1:]) if len(lines) > 1 else ""
                _set_formtext_values_in_container(prose_form_paras[second_para_idx], [rest_text])

    out_xml = tostring(root, encoding="utf-8", xml_declaration=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("word/document.xml", out_xml)
        for name, data in other_entries.items():
            zout.writestr(name, data)
    return buf.getvalue()


def render_australia_awards(content: CVContent) -> RenderedArtifact:
    """Render the Australia Awards CV template to a PDF + field_mapped artifact."""
    clean = hygienic_content(content)
    fields = australia_awards_fields(clean)
    html = render_to_string(
        "documents/cv_funder_australia_awards.html",
        {
            "content": clean,
            "fields": fields,
        },
    )
    artifact = render_html_to_artifact(html, variant="FUNDER_TEMPLATE")
    return replace(artifact, field_mapped=fields)
