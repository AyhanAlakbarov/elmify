"""PDF form inspection and AcroForm filling."""

from __future__ import annotations

import io
import zlib
from collections.abc import Mapping, Sequence
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError
from pypdf.generic import ArrayObject, BooleanObject, DictionaryObject, NameObject

from apps.documents.hygiene import scrub_pdf_metadata

from .models import (
    FormSlot,
    PdfFormInspection,
    PdfFormKind,
    SlotKind,
    UnsupportedFormFormat,
    _match_dropdown_option,
    _parse_checkbox_bool,
)


def _pdf_has_xfa(reader: PdfReader) -> bool:
    root = reader.root_object
    acroform = root.get("/AcroForm")
    if acroform is not None and hasattr(acroform, "get_object"):
        acroform = acroform.get_object()
    return isinstance(acroform, DictionaryObject) and "/XFA" in acroform


def _pdf_button_states(field: Mapping[str, Any]) -> tuple[str, ...]:
    states = field.get("/_States_")
    if isinstance(states, list | tuple | ArrayObject):
        extracted = [str(s) for s in states if str(s)]
        if extracted:
            return tuple(dict.fromkeys(extracted))
    ap = field.get("/AP")
    if ap is not None and hasattr(ap, "get_object"):
        ap = ap.get_object()
    if isinstance(ap, DictionaryObject):
        normal = ap.get("/N")
        if normal is not None and hasattr(normal, "get_object"):
            normal = normal.get_object()
        if isinstance(normal, DictionaryObject):
            return tuple(str(k) for k in normal.keys())
    return ("/Yes", "/Off")


def _pdf_choice_options(field: Mapping[str, Any]) -> tuple[str, ...]:
    opt = field.get("/Opt")
    if opt is not None and hasattr(opt, "get_object"):
        opt = opt.get_object()
    if not isinstance(opt, list | tuple | ArrayObject):
        return ()
    options: list[str] = []
    for item in opt:
        if hasattr(item, "get_object"):
            item = item.get_object()
        if isinstance(item, list | tuple | ArrayObject) and len(item) >= 2:
            options.append(str(item[-1]).strip())
        else:
            options.append(str(item).strip())
    return tuple(o for o in options if o)


_MAX_FORM_PDF_PAGES = 50


def _pdf_has_extractable_text(reader: PdfReader) -> bool:
    for page in reader.pages[:5]:
        if (page.extract_text() or "").strip():
            return True
    return False


def inspect_pdf_slots(pdf_bytes: bytes) -> PdfFormInspection:
    """Inspect a PDF for `/AcroForm` fields, Adobe `/XFA` streams, or flat/scanned state."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if len(reader.pages) > _MAX_FORM_PDF_PAGES:
            raise ValueError("PDF has too many pages.")
        is_xfa = _pdf_has_xfa(reader)
        raw_fields = reader.get_fields() or {}
    except (
        PyPdfError,
        zlib.error,
        EOFError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        AttributeError,
    ) as exc:
        raise ValueError("corrupt or unreadable PDF") from exc
    slots: list[FormSlot] = []
    for name, field in raw_fields.items():
        if not isinstance(field, dict):
            continue
        ft = str(field.get("/FT") or "/Tx")
        tooltip = str(field.get("/TU") or "").strip()
        val = str(field.get("/V") or "").strip()
        if ft == "/Btn":
            kind: SlotKind = "pdf_checkbox"
            options = _pdf_button_states(field)
        elif ft == "/Ch":
            kind = "pdf_dropdown"
            options = _pdf_choice_options(field)
        else:
            kind = "pdf_text"
            options = ()
        slots.append(
            FormSlot(
                slot_id=str(name),
                kind=kind,
                label=tooltip or str(name),
                current_value=val,
                options=options,
            )
        )
    if is_xfa:
        pdf_kind: PdfFormKind = "xfa"
    elif slots:
        pdf_kind = "acroform"
    elif _pdf_has_extractable_text(reader):
        pdf_kind = "flat_text"
    else:
        pdf_kind = "scanned_image"
    return PdfFormInspection(slots=tuple(slots), is_xfa=is_xfa, pdf_kind=pdf_kind)


def _resolve_pdf_checkbox_state(raw_val: str, options: Sequence[str]) -> str:
    clean = raw_val.strip()
    for opt in options:
        if clean == opt or f"/{clean}" == opt:
            return opt if opt.startswith("/") else f"/{opt}"
    is_checked = _parse_checkbox_bool(clean)
    if not is_checked:
        return "/Off"
    for opt in options:
        if opt.casefold() != "/off" and opt.casefold() != "off":
            return opt if opt.startswith("/") else f"/{opt}"
    return "/Yes"


def fill_pdf_slots(pdf_bytes: bytes, values: Mapping[str, str]) -> bytes:
    """Populate fillable `/AcroForm` fields in `pdf_bytes` and return the updated PDF.

    Raises `UnsupportedFormFormat` when the PDF is an Adobe XFA dynamic form or
    carries no `/AcroForm` fields (`flat_text` or `scanned_image`), so callers
    never silently emit an unfilled file.
    """
    inspection = inspect_pdf_slots(pdf_bytes)
    if inspection.is_xfa:
        raise UnsupportedFormFormat(
            "PDF uses Adobe XFA dynamic form streams; emit FIELD_MAPPED copy-paste output instead"
        )
    if not inspection.slots:
        raise UnsupportedFormFormat(
            f"PDF contains no fillable AcroForm fields (detected kind: {inspection.pdf_kind})"
        )

    slot_map = {s.slot_id: s for s in inspection.slots}
    normalized_values: dict[str, str] = {}
    checkbox_states: dict[str, str] = {}

    for key, raw_val in values.items():
        slot = slot_map.get(key)
        if slot is None:
            normalized_values[key] = raw_val
            continue
        if slot.kind == "pdf_checkbox":
            state_name = _resolve_pdf_checkbox_state(raw_val, slot.options)
            normalized_values[key] = state_name
            checkbox_states[key] = state_name
        elif slot.kind == "pdf_dropdown" and slot.options:
            _, matched = _match_dropdown_option(raw_val, slot.options, allow_custom=False)
            normalized_values[key] = matched
        else:
            normalized_values[key] = raw_val

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter(clone_from=reader)
    writer.update_page_form_field_values(None, normalized_values, auto_regenerate=True)

    # Ensure /NeedAppearances is set on /AcroForm and update /AS + /V on checkbox widgets
    acroform = writer._root_object.get("/AcroForm")
    if acroform is not None and hasattr(acroform, "get_object"):
        acroform = acroform.get_object()
    if isinstance(acroform, DictionaryObject):
        acroform[NameObject("/NeedAppearances")] = BooleanObject(True)

    if checkbox_states:
        for page in writer.pages:
            annots = page.get("/Annots")
            if not isinstance(annots, list | ArrayObject):
                continue
            for annot_ref in annots:
                annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
                if not isinstance(annot, DictionaryObject):
                    continue
                field_name = str(annot.get("/T") or "")
                if field_name in checkbox_states:
                    name_obj = NameObject(checkbox_states[field_name])
                    annot[NameObject("/V")] = name_obj
                    annot[NameObject("/AS")] = name_obj

    out = io.BytesIO()
    writer.write(out)
    return scrub_pdf_metadata(out.getvalue())
