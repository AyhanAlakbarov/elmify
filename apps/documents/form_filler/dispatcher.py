"""Form dispatching and fill execution for docx and pdf templates."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence

from apps.documents.hygiene import normalize_text
from apps.documents.models import VerifiedFact

from .docx import fill_docx_slots, inspect_docx_slots
from .fact_mapping import map_student_facts_to_slots
from .models import (
    FormFillResult,
    FormSlot,
    UnsupportedFormFormat,
    _ascii_label_key,
    _norm_label_key,
)
from .pdf import fill_pdf_slots, inspect_pdf_slots

logger = logging.getLogger(__name__)

def _resolve_slot_values(
    slots: Sequence[FormSlot],
    values: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve `values` keyed by either `slot_id` or `label` into `(by_slot_id, by_label)`."""
    clean_input = {k: normalize_text(str(v)) for k, v in values.items()}
    norm_input: dict[str, str] = {}
    for k, v in clean_input.items():
        ukey = _norm_label_key(k)
        akey = _ascii_label_key(k)
        if ukey:
            norm_input[ukey] = v
        if akey:
            norm_input.setdefault(akey, v)
    by_slot_id: dict[str, str] = {}
    by_label: dict[str, str] = {}

    for slot in slots:
        matched_val: str | None = None
        if slot.slot_id in clean_input:
            matched_val = clean_input[slot.slot_id]
        elif slot.label in clean_input:
            matched_val = clean_input[slot.label]
        else:
            head_raw = slot.label.split("—", 1)[0]
            for candidate_key in (
                _norm_label_key(slot.label),
                _ascii_label_key(slot.label),
                _norm_label_key(head_raw),
                _ascii_label_key(head_raw),
            ):
                if candidate_key and candidate_key in norm_input:
                    matched_val = norm_input[candidate_key]
                    break
        if matched_val is not None:
            by_slot_id[slot.slot_id] = matched_val
            by_label[slot.label] = matched_val

    for k, v in clean_input.items():
        if k.startswith(("ff:", "sdt:", "cell:")) and k not in by_slot_id:
            by_slot_id[k] = v
            by_label.setdefault(k, v)

    return by_slot_id, by_label


def fill_form_template(
    template_bytes: bytes,
    values: Mapping[str, str],
) -> FormFillResult:
    """End-to-end form pipeline: inspect a `.docx` or `.pdf` template, resolve
    `values` (by `slot_id` or human label) with text hygiene, populate the template
    in place when supported, or degrade cleanly to `field_mapped_fallback` when the
    template is an XFA, flat, or scanned PDF."""
    is_pdf = template_bytes.lstrip().startswith(b"%PDF-")
    if not is_pdf:
        slots = inspect_docx_slots(template_bytes)
        by_slot_id, by_label = _resolve_slot_values(slots, values)
        filled_docx = fill_docx_slots(template_bytes, by_slot_id)
        return FormFillResult(
            mode="docx_filled",
            filled_bytes=filled_docx,
            field_mapped=by_label,
            slots=slots,
        )

    inspection = inspect_pdf_slots(template_bytes)
    by_slot_id, by_label = _resolve_slot_values(inspection.slots, values)
    if not by_label and values:
        by_label = {str(k): normalize_text(str(v)) for k, v in values.items()}
    try:
        filled_pdf = fill_pdf_slots(template_bytes, by_slot_id)
    except UnsupportedFormFormat as exc:
        logger.warning("form_filler degraded to field_mapped_fallback: %s", exc)
        return FormFillResult(
            mode="field_mapped_fallback",
            filled_bytes=None,
            field_mapped=by_label,
            slots=inspection.slots,
            fallback_reason=str(exc),
        )
    return FormFillResult(
        mode="pdf_filled",
        filled_bytes=filled_pdf,
        field_mapped=by_label,
        slots=inspection.slots,
    )



def fill_student_form_template(
    template_bytes: bytes,
    *,
    facts: Iterable[VerifiedFact],
    student_name: str = "",
    student_email: str = "",
    target_programme: str = "",
    target_institution: str = "",
    passport_details: Mapping[str, str] | None = None,
    overrides: Mapping[str, str] | None = None,
) -> FormFillResult:
    """Inspect an arbitrary `.docx` or `.pdf` template, auto-map the student's confirmed
    `VerifiedFact` rows and passport details onto its slots, merge any explicit `overrides`,
    and populate the document (or return `field_mapped_fallback` for XFA/scanned PDFs)."""
    is_pdf = template_bytes.lstrip().startswith(b"%PDF-")
    slots = (
        inspect_pdf_slots(template_bytes).slots
        if is_pdf
        else inspect_docx_slots(template_bytes)
    )
    auto_values = map_student_facts_to_slots(
        slots,
        facts=facts,
        student_name=student_name,
        student_email=student_email,
        target_programme=target_programme,
        target_institution=target_institution,
        passport_details=passport_details,
    )
    merged: dict[str, str] = dict(auto_values)
    if overrides:
        for k, v in overrides.items():
            if str(v).strip():
                merged[str(k)] = str(v)
    return fill_form_template(template_bytes, merged)

