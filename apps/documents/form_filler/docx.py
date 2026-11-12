"""DOCX form inspection and deterministic slot/table filling."""

from __future__ import annotations

import copy
import io
import re
import zipfile
import zlib
from collections.abc import Mapping, Sequence
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring  # nosec B405

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from .models import (
    _GENERIC_PLACEHOLDERS,
    FormSlot,
    _match_dropdown_option,
    _parse_checkbox_bool,
)

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
_W = f"{{{_W_NS}}}"
_W14 = f"{{{_W14_NS}}}"
register_namespace("w", _W_NS)
register_namespace("w14", _W14_NS)

_MAX_DOCX_ENTRIES = 500
_MAX_DOCX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
_HEADER_FOOTER_RE = re.compile(r"^word/(header|footer)\d*\.xml$")
_INSTRUCTIONAL_CELL_RE = re.compile(
    r"^(?:replace\s+with\b|click\s+(?:or\s+tap\s+)?here\s+to\s+enter\b|"
    r"insert\s+text\s+response\s+here\b|klicken\s+(?:oder\s+tippen\s+)?sie\s+hier\b|"
    r"cliquez\s+(?:ou\s+appuyez\s+)?ici\b|haga\s+clic\s+(?:o\s+pulse\s+)?aqu[ií]\b|"
    r"\[[^\[\]\n]{2,80}\]$|<[^<>\n]{2,80}>$)",
    re.IGNORECASE,
)


def _validate_docx_archive(zin: zipfile.ZipFile) -> None:
    infos = zin.infolist()
    if len(infos) > _MAX_DOCX_ENTRIES:
        raise ValueError(f"docx archive has too many entries ({len(infos)})")
    total_size = 0
    for info in infos:
        name = info.filename
        if name.startswith("/") or ".." in name.split("/"):
            raise ValueError(f"unsafe zip entry path: {name!r}")
        if info.file_size < 0:
            raise ValueError(f"invalid zip entry size for {name!r}")
        total_size += info.file_size
        if total_size > _MAX_DOCX_UNCOMPRESSED_BYTES:
            raise ValueError("docx uncompressed size exceeds safety limit")
    if "word/document.xml" not in zin.namelist():
        raise ValueError("not a valid .docx archive: missing word/document.xml")


def _read_zip_member(
    zin: zipfile.ZipFile, name: str, *, max_bytes: int = _MAX_DOCX_UNCOMPRESSED_BYTES
) -> bytes:
    """Read a member from `zin` enforcing `max_bytes` on the actual decompressed stream
    (never trusting `ZipInfo.file_size` from the central directory header alone)."""
    try:
        with zin.open(name, "r") as member:
            data = member.read(max_bytes + 1)
    except (zipfile.BadZipFile, zlib.error, EOFError, KeyError, RuntimeError) as exc:
        raise ValueError(f"corrupt .docx archive member {name!r}") from exc
    if len(data) > max_bytes:
        raise ValueError("docx uncompressed size exceeds safety limit")
    return data


def _parse_docx_xml(xml_bytes: bytes) -> Element:
    try:
        return DefusedET.fromstring(xml_bytes)
    except (DefusedET.ParseError, DefusedXmlException, SyntaxError) as exc:
        raise ValueError("corrupt or unsafe XML in .docx archive") from exc


def _docx_xml_parts(zin: zipfile.ZipFile) -> list[str]:
    names = zin.namelist()
    extra = sorted(n for n in names if _HEADER_FOOTER_RE.match(n))
    return ["word/document.xml", *extra]


def _part_prefix(part_name: str) -> str:
    if part_name == "word/document.xml":
        return ""
    stem = part_name.removeprefix("word/").removesuffix(".xml")
    return f"{stem}:"


def _element_text(elem: Element) -> str:
    return "".join((t.text or "") for t in elem.iter(f"{_W}t")).strip()


def _direct_cell_text(cell: Element) -> str:
    """Return text from direct `<w:p>` children of `cell`, excluding nested `<w:tbl>`."""
    parts = [
        "".join((t.text or "") for t in p.iter(f"{_W}t")).strip()
        for p in cell.findall(f"{_W}p")
    ]
    return " ".join(p for p in parts if p).strip()


def _disambiguate_id(base_id: str, seen_counts: dict[str, int]) -> str:
    count = seen_counts.get(base_id, 0) + 1
    seen_counts[base_id] = count
    return base_id if count == 1 else f"{base_id}_{count}"


def _ffdata_base_name(ff_data: Element, index: int) -> str:
    name_el = ff_data.find(f"{_W}name")
    val = name_el.get(f"{_W}val", "").strip() if name_el is not None else ""
    return f"ff:{val}" if val else f"ff:{index}"


def _ffdata_explicit_label(ff_data: Element) -> str:
    status_el = ff_data.find(f"{_W}statusText")
    help_el = ff_data.find(f"{_W}helpText")
    for hint in (status_el, help_el):
        if hint is not None and hint.get(f"{_W}val"):
            return str(hint.get(f"{_W}val")).strip()
    return ""


def _sdt_base_id_and_label(sdt: Element, index: int) -> tuple[str, str]:
    pr = sdt.find(f"{_W}sdtPr")
    tag = ""
    alias = ""
    if pr is not None:
        tag_el = pr.find(f"{_W}tag")
        alias_el = pr.find(f"{_W}alias")
        if tag_el is not None:
            tag = (tag_el.get(f"{_W}val") or "").strip()
        if alias_el is not None:
            alias = (alias_el.get(f"{_W}val") or "").strip()
    key = tag or alias or str(index)
    explicit_label = alias or tag
    return f"sdt:{key}", explicit_label


def _cell_grid_span(cell: Element) -> int:
    tc_pr = cell.find(f"{_W}tcPr")
    if tc_pr is None:
        return 1
    span_el = tc_pr.find(f"{_W}gridSpan")
    if span_el is None:
        return 1
    raw_val = span_el.get(f"{_W}val", "1")
    try:
        return max(1, int(raw_val))
    except ValueError:
        return 1


def _is_vmerge_continue(cell: Element) -> bool:
    tc_pr = cell.find(f"{_W}tcPr")
    if tc_pr is None:
        return False
    vmerge = tc_pr.find(f"{_W}vMerge")
    if vmerge is None:
        return False
    val = (vmerge.get(f"{_W}val") or "").strip().casefold()
    return val != "restart"


def _row_grid_headers(
    cells: Sequence[Element],
    cell_texts: Sequence[str],
    *,
    skip_instructional: bool = False,
) -> dict[int, str]:
    col_headers: dict[int, str] = {}
    grid_col = 0
    for c_idx, cell in enumerate(cells):
        span = _cell_grid_span(cell)
        hdr = cell_texts[c_idx]
        if not (skip_instructional and _INSTRUCTIONAL_CELL_RE.match(hdr)):
            for g in range(grid_col, grid_col + span):
                col_headers[g] = hdr
        grid_col += span
    return col_headers


def _build_context_labels(root: Element) -> dict[int, str]:
    """Map `id(elem)` of `<w:ffData>` and `<w:sdt>` elements to their contextual
    table cell or paragraph heading label when they carry no explicit label."""
    context_map: dict[int, str] = {}

    # 1. Table cell context (left label cell + column header)
    for tbl in root.iter(f"{_W}tbl"):
        rows = tbl.findall(f"{_W}tr")
        col_headers_by_grid: dict[int, str] = {}
        for r_idx, row in enumerate(rows):
            cells = row.findall(f"{_W}tc")
            cell_texts = [_direct_cell_text(c) for c in cells]
            if r_idx == 0:
                col_headers_by_grid = _row_grid_headers(cells, cell_texts)
            grid_col = 0

            for c_idx, cell in enumerate(cells):
                span = _cell_grid_span(cell)
                current_grid_col = grid_col
                grid_col += span
                left_label = (
                    cell_texts[c_idx - 1]
                    if c_idx > 0
                    and cell_texts[c_idx - 1]
                    and cell_texts[c_idx - 1].casefold() not in _GENERIC_PLACEHOLDERS
                    and not _INSTRUCTIONAL_CELL_RE.match(cell_texts[c_idx - 1])
                    else ""
                )
                top_label = col_headers_by_grid.get(current_grid_col, "") if r_idx > 0 else ""
                # Only use left_label when the cell is in a 2-column key-value table or
                # top_label is generic ("Applicant Details", "Applicant Answer").
                if top_label and left_label and len(cells) > 2:
                    base_label = top_label
                else:
                    base_label = " — ".join(p for p in (left_label, top_label) if p)

                for ff in cell.iter(f"{_W}ffData"):
                    context_map[id(ff)] = base_label
                for sdt in cell.iter(f"{_W}sdt"):
                    sdt_text = _element_text(sdt)
                    own_prefix = cell_texts[c_idx].replace(sdt_text, "").strip(" |:-–—")
                    context_map[id(sdt)] = own_prefix or base_label

    # 2. Top-level body paragraph context (nearest preceding heading/label paragraph)
    body = root.find(f"{_W}body")
    if body is not None:
        last_heading = ""
        for child in body:
            if child.tag != f"{_W}p":
                continue
            has_control = (
                child.find(f".//{_W}ffData") is not None
                or child.find(f".//{_W}sdt") is not None
            )
            p_text = _element_text(child)
            if not has_control:
                if p_text and p_text.casefold() not in _GENERIC_PLACEHOLDERS:
                    last_heading = p_text
            elif last_heading:
                for ff in child.iter(f"{_W}ffData"):
                    context_map.setdefault(id(ff), last_heading)
                for sdt in child.iter(f"{_W}sdt"):
                    context_map.setdefault(id(sdt), last_heading)

    return context_map


def _extract_formtext_results(root: Element) -> list[str]:
    """Return the displayed text between `separate` and `end` for each `<w:ffData>`."""
    results: list[str] = []
    in_ff = False
    in_result = False
    buf: list[str] = []
    for elem in root.iter():
        if elem.tag == f"{_W}ffData":
            if (
                elem.find(f"{_W}textInput") is not None
                or elem.find(f"{_W}checkBox") is not None
                or elem.find(f"{_W}ddList") is not None
            ):
                in_ff = True
                in_result = False
                buf = []
        elif elem.tag == f"{_W}fldChar" and in_ff:
            fld_type = elem.get(f"{_W}fldCharType")
            if fld_type == "separate":
                in_result = True
            elif fld_type == "end":
                results.append("".join(buf).strip())
                in_ff = False
                in_result = False
                buf = []
        elif elem.tag == f"{_W}t" and in_result:
            buf.append(elem.text or "")
    return results


def _is_section_banner_table(rows: Sequence[Element]) -> bool:
    if len(rows) != 1:
        return False
    cells = rows[0].findall(f"{_W}tc")
    if len(cells) != 2:
        return False
    if cells[0].find(f"{_W}tbl") is not None or cells[1].find(f"{_W}tbl") is not None:
        return True
    left_txt = _direct_cell_text(cells[0])
    right_txt = _direct_cell_text(cells[1])
    return bool(left_txt and not right_txt and ":" not in left_txt and left_txt.isupper())


def _inspect_ffdata_slot(
    elem: Element,
    *,
    slot_id: str,
    label: str,
    ctx_label: str,
    displayed_val: str,
    text_input: Element | None,
    checkbox: Element | None,
    dd_list: Element | None,
) -> FormSlot:
    if checkbox is not None:
        checked_el = checkbox.find(f"{_W}checked")
        default_el = checkbox.find(f"{_W}default")
        raw_chk = ""
        if checked_el is not None and checked_el.get(f"{_W}val") is not None:
            raw_chk = str(checked_el.get(f"{_W}val"))
        elif default_el is not None and default_el.get(f"{_W}val") is not None:
            raw_chk = str(default_el.get(f"{_W}val"))
        current_val = "true" if raw_chk.strip() in {"1", "true"} else "false"
        return FormSlot(
            slot_id=slot_id,
            kind="docx_checkbox",
            label=label,
            current_value=current_val,
        )
    if dd_list is not None:
        entries = tuple(
            str(entry.get(f"{_W}val") or "").strip()
            for entry in dd_list.findall(f"{_W}listEntry")
            if entry.get(f"{_W}val") is not None
        )
        res_el = dd_list.find(f"{_W}result")
        current_opt = ""
        if res_el is not None and res_el.get(f"{_W}val") is not None:
            try:
                idx = int(str(res_el.get(f"{_W}val")))
                if 0 <= idx < len(entries):
                    current_opt = entries[idx]
            except ValueError:
                current_opt = ""
        return FormSlot(
            slot_id=slot_id,
            kind="docx_dropdown",
            label=label,
            current_value=current_opt,
            options=entries,
        )
    default_txt_el = text_input.find(f"{_W}default") if text_input is not None else None
    default_txt = (
        str(default_txt_el.get(f"{_W}val") or "").strip()
        if default_txt_el is not None
        else ""
    )
    current_txt = default_txt or displayed_val
    if current_txt in {"DD", "MM", "YYYY"} and ctx_label and current_txt not in label:
        label = f"{ctx_label} — {current_txt}"
    return FormSlot(
        slot_id=slot_id,
        kind="docx_formtext",
        label=label,
        current_value=current_txt,
    )


def _inspect_sdt_slot(sdt: Element, *, slot_id: str, label: str) -> FormSlot:
    pr = sdt.find(f"{_W}sdtPr")
    content = sdt.find(f"{_W}sdtContent")
    current = _element_text(content) if content is not None else ""
    w14_cb = pr.find(f"{_W14}checkbox") if pr is not None else None
    dd_list = pr.find(f"{_W}dropDownList") if pr is not None else None
    dd_ctrl = (
        dd_list
        if dd_list is not None
        else (pr.find(f"{_W}comboBox") if pr is not None else None)
    )
    if w14_cb is not None:
        chk_el = w14_cb.find(f"{_W14}checked")
        chk_attr = (
            str(chk_el.get(f"{_W14}val") or chk_el.get(f"{_W}val") or "").strip()
            if chk_el is not None
            else ""
        )
        is_checked = chk_attr in {"1", "true"} or current in {"☒", "☑"}
        return FormSlot(
            slot_id=slot_id,
            kind="docx_checkbox",
            label=label,
            current_value="true" if is_checked else "false",
        )
    if dd_ctrl is not None:
        opts = tuple(
            disp
            for item in dd_ctrl.findall(f"{_W}listItem")
            if (disp := (item.get(f"{_W}displayText") or item.get(f"{_W}value") or "").strip())
        )
        return FormSlot(
            slot_id=slot_id,
            kind="docx_dropdown",
            label=label,
            current_value=current,
            options=opts,
        )
    return FormSlot(
        slot_id=slot_id,
        kind="docx_sdt",
        label=label,
        current_value=current,
    )


def _inspect_table_cell_slots(root: Element) -> list[FormSlot]:
    cell_slots: list[FormSlot] = []
    for t_idx, tbl in enumerate(root.iter(f"{_W}tbl")):
        rows = tbl.findall(f"{_W}tr")
        if _is_section_banner_table(rows):
            continue
        col_headers_by_grid: dict[int, str] = {}
        for r_idx, row in enumerate(rows):
            cells = row.findall(f"{_W}tc")
            cell_texts = [_direct_cell_text(c) for c in cells]
            if r_idx == 0:
                col_headers_by_grid = _row_grid_headers(
                    cells, cell_texts, skip_instructional=True
                )
            grid_col = 0
            for c_idx, cell in enumerate(cells):
                span = _cell_grid_span(cell)
                current_grid_col = grid_col
                grid_col += span
                if (
                    cell.find(f"{_W}tbl") is not None
                    or _is_vmerge_continue(cell)
                    or cell.find(f".//{_W}ffData") is not None
                    or cell.find(f".//{_W}sdt") is not None
                ):
                    continue
                own_txt = cell_texts[c_idx]
                is_instructional = bool(own_txt and _INSTRUCTIONAL_CELL_RE.match(own_txt))
                if (own_txt and not is_instructional) or (not is_instructional and c_idx == 0):
                    continue
                left_raw = cell_texts[c_idx - 1] if c_idx > 0 else ""
                left_label = (
                    left_raw if left_raw and not _INSTRUCTIONAL_CELL_RE.match(left_raw) else ""
                )
                top_label = col_headers_by_grid.get(current_grid_col, "") if r_idx > 0 else ""
                header_label = " — ".join(part for part in (left_label, top_label) if part)
                label = (
                    " — ".join(part for part in (header_label, own_txt) if part)
                    if is_instructional
                    else header_label
                )
                if not label:
                    continue
                cell_slots.append(
                    FormSlot(
                        slot_id=f"cell:t{t_idx}_r{r_idx}_c{c_idx}",
                        kind="docx_table_cell",
                        label=label,
                        current_value=own_txt if is_instructional else "",
                    )
                )
    return cell_slots


def _inspect_part_slots(
    root: Element,
    *,
    part_prefix: str,
    ff_start: int,
    sdt_start: int,
    seen_ids: dict[str, int],
) -> tuple[list[FormSlot], int, int]:
    slots: list[FormSlot] = []
    ff_index = ff_start
    sdt_index = sdt_start
    context_labels = _build_context_labels(root)
    ff_displayed = _extract_formtext_results(root)
    local_ff_ord = 0

    for elem in root.iter(f"{_W}ffData"):
        text_input = elem.find(f"{_W}textInput")
        checkbox = elem.find(f"{_W}checkBox")
        dd_list = elem.find(f"{_W}ddList")
        if text_input is None and checkbox is None and dd_list is None:
            continue
        base_id = _ffdata_base_name(elem, ff_index)
        slot_id = _disambiguate_id(base_id, seen_ids)
        displayed_val = ff_displayed[local_ff_ord] if local_ff_ord < len(ff_displayed) else ""
        local_ff_ord += 1
        ctx_label = context_labels.get(id(elem), "")
        label = _ffdata_explicit_label(elem) or ctx_label or slot_id
        slots.append(
            _inspect_ffdata_slot(
                elem,
                slot_id=slot_id,
                label=label,
                ctx_label=ctx_label,
                displayed_val=displayed_val,
                text_input=text_input,
                checkbox=checkbox,
                dd_list=dd_list,
            )
        )
        ff_index += 1

    for sdt in root.iter(f"{_W}sdt"):
        base_id, explicit_label = _sdt_base_id_and_label(sdt, sdt_index)
        slot_id = _disambiguate_id(base_id, seen_ids)
        ctx_label = context_labels.get(id(sdt), "")
        label = explicit_label or ctx_label or f"Content control {sdt_index}"
        slots.append(_inspect_sdt_slot(sdt, slot_id=slot_id, label=label))
        sdt_index += 1

    if not part_prefix:
        slots.extend(_inspect_table_cell_slots(root))

    return slots, ff_index, sdt_index


def inspect_docx_slots(docx_bytes: bytes) -> tuple[FormSlot, ...]:
    """Extract all fillable slots (`FORMTEXT`, checkboxes, dropdowns, `w:sdt`, and
    empty or placeholder labeled table cells) from `docx_bytes`."""
    try:
        zin_ctx = zipfile.ZipFile(io.BytesIO(docx_bytes), "r")
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise ValueError("not a valid .docx archive") from exc
    with zin_ctx as zin:
        _validate_docx_archive(zin)
        parts = _docx_xml_parts(zin)
        all_slots: list[FormSlot] = []
        ff_idx = 0
        sdt_idx = 0
        seen_ids: dict[str, int] = {}
        remaining = _MAX_DOCX_UNCOMPRESSED_BYTES
        for part_name in parts:
            raw_part = _read_zip_member(zin, part_name, max_bytes=remaining)
            remaining -= len(raw_part)
            root = _parse_docx_xml(raw_part)
            part_slots, ff_idx, sdt_idx = _inspect_part_slots(
                root,
                part_prefix=_part_prefix(part_name),
                ff_start=ff_idx,
                sdt_start=sdt_idx,
                seen_ids=seen_ids,
            )
            all_slots.extend(part_slots)

    return tuple(all_slots)


def _set_cell_or_container_text(container: Element, value: str) -> None:
    t_elems = list(container.iter(f"{_W}t"))
    if t_elems:
        t_elems[0].text = value
        for extra in t_elems[1:]:
            extra.text = ""
        return
    p = container.find(f"{_W}p")
    if p is None:
        p = SubElement(container, f"{_W}p")
    r = p.find(f"{_W}r")
    if r is None:
        r = SubElement(p, f"{_W}r")
    t = SubElement(r, f"{_W}t")
    t.text = value


def _fill_ffdata_control(
    raw_val: str,
    chosen_ff_key: str,
    *,
    text_input: Element | None,
    checkbox: Element | None,
    dd_list: Element | None,
) -> str | None:
    if checkbox is not None:
        bit = "1" if _parse_checkbox_bool(raw_val) else "0"
        checked_el = checkbox.find(f"{_W}checked")
        if checked_el is None:
            checked_el = SubElement(checkbox, f"{_W}checked")
        checked_el.set(f"{_W}val", bit)
        default_el = checkbox.find(f"{_W}default")
        if default_el is not None:
            default_el.set(f"{_W}val", bit)
        return None
    if dd_list is not None:
        entries = [
            str(entry.get(f"{_W}val") or "").strip()
            for entry in dd_list.findall(f"{_W}listEntry")
            if entry.get(f"{_W}val") is not None
        ]
        idx, _ = _match_dropdown_option(raw_val, entries, allow_custom=False)
        res_el = dd_list.find(f"{_W}result")
        if res_el is None:
            res_el = SubElement(dd_list, f"{_W}result")
        res_el.set(f"{_W}val", str(idx))
        return None
    if text_input is not None:
        default_el = text_input.find(f"{_W}default")
        if default_el is None:
            default_el = SubElement(text_input, f"{_W}default")
        default_el.set(f"{_W}val", raw_val)
    return chosen_ff_key


def _insert_missing_formtext_run(
    elem: Element,
    current_run: Element | None,
    parent_map: Mapping[Element, Element],
    value: str,
) -> None:
    run_parent = parent_map.get(current_run) if current_run is not None else None
    if run_parent is not None and current_run is not None:
        new_run = Element(f"{_W}r")
        t_el = SubElement(new_run, f"{_W}t")
        t_el.text = value
        children = list(run_parent)
        insert_at = children.index(current_run) if current_run in children else len(children)
        run_parent.insert(insert_at, new_run)
    else:
        t_el = SubElement(elem, f"{_W}t")
        t_el.text = value


def _fill_sdt_control(sdt: Element, raw_val: str) -> None:
    pr = sdt.find(f"{_W}sdtPr")
    content = sdt.find(f"{_W}sdtContent")
    if content is None:
        content = SubElement(sdt, f"{_W}sdtContent")
    w14_cb = pr.find(f"{_W14}checkbox") if pr is not None else None
    dd_list_ctrl = pr.find(f"{_W}dropDownList") if pr is not None else None
    combo_ctrl = pr.find(f"{_W}comboBox") if pr is not None else None

    if w14_cb is not None:
        checked_bool = _parse_checkbox_bool(raw_val)
        chk_el = w14_cb.find(f"{_W14}checked")
        if chk_el is None:
            chk_el = SubElement(w14_cb, f"{_W14}checked")
        chk_el.set(f"{_W14}val", "1" if checked_bool else "0")
        _set_cell_or_container_text(content, "☒" if checked_bool else "☐")
        return
    if dd_list_ctrl is not None or combo_ctrl is not None:
        ctrl = dd_list_ctrl if dd_list_ctrl is not None else combo_ctrl
        assert ctrl is not None
        opts: list[str] = []
        val_to_display: dict[str, str] = {}
        for item in ctrl.findall(f"{_W}listItem"):
            disp = (item.get(f"{_W}displayText") or item.get(f"{_W}value") or "").strip()
            item_val = (item.get(f"{_W}value") or disp).strip()
            if disp:
                opts.append(disp)
            if item_val:
                val_to_display[item_val.casefold()] = disp or item_val
        mapped_input = val_to_display.get(raw_val.strip().casefold(), raw_val)
        _, chosen_text = _match_dropdown_option(
            mapped_input,
            opts,
            allow_custom=(combo_ctrl is not None),
        )
        _set_cell_or_container_text(content, chosen_text)
        return
    _set_cell_or_container_text(content, raw_val)


def _fill_part_slots(
    root: Element,
    values: Mapping[str, str],
    *,
    part_prefix: str,
    ff_start: int,
    sdt_start: int,
    seen_ids: dict[str, int],
) -> tuple[int, int]:
    ff_index = ff_start
    sdt_index = sdt_start

    active_slot_id: str | None = None
    in_result = False
    wrote_result = False
    parent_map = {child: parent for parent in root.iter() for child in parent}
    current_run: Element | None = None

    for elem in list(root.iter()):
        tag = elem.tag
        if tag == f"{_W}r":
            current_run = elem
        elif tag == f"{_W}ffData":
            text_input = elem.find(f"{_W}textInput")
            checkbox = elem.find(f"{_W}checkBox")
            dd_list = elem.find(f"{_W}ddList")
            if text_input is None and checkbox is None and dd_list is None:
                continue
            slot_id = _disambiguate_id(_ffdata_base_name(elem, ff_index), seen_ids)
            fallback_id = f"ff:{ff_index}"
            chosen_ff_key = (
                slot_id
                if slot_id in values
                else (fallback_id if fallback_id in values else None)
            )
            ff_index += 1
            if chosen_ff_key is None:
                active_slot_id = None
                continue
            active_slot_id = _fill_ffdata_control(
                values[chosen_ff_key],
                chosen_ff_key,
                text_input=text_input,
                checkbox=checkbox,
                dd_list=dd_list,
            )
        elif tag == f"{_W}fldChar":
            fld_type = elem.get(f"{_W}fldCharType")
            if fld_type == "separate" and active_slot_id is not None:
                in_result = True
                wrote_result = False
            elif fld_type == "end":
                if active_slot_id is not None and not wrote_result:
                    _insert_missing_formtext_run(
                        elem, current_run, parent_map, values[active_slot_id]
                    )
                active_slot_id = None
                in_result = False
                wrote_result = False
        elif tag == f"{_W}t" and in_result and active_slot_id is not None:
            elem.text = values[active_slot_id] if not wrote_result else ""
            wrote_result = True

    for sdt in root.iter(f"{_W}sdt"):
        base_id, _ = _sdt_base_id_and_label(sdt, sdt_index)
        slot_id = _disambiguate_id(base_id, seen_ids)
        fallback_id = f"sdt:{sdt_index}"
        sdt_index += 1
        chosen_key = (
            slot_id if slot_id in values else (fallback_id if fallback_id in values else "")
        )
        if chosen_key:
            _fill_sdt_control(sdt, values[chosen_key])

    for t_idx, tbl in enumerate(root.iter(f"{_W}tbl")):
        for r_idx, row in enumerate(tbl.findall(f"{_W}tr")):
            for c_idx, cell in enumerate(row.findall(f"{_W}tc")):
                cell_key = f"{part_prefix}cell:t{t_idx}_r{r_idx}_c{c_idx}"
                if cell_key in values:
                    _set_cell_or_container_text(cell, values[cell_key])

    return ff_index, sdt_index


def fill_docx_slots(docx_bytes: bytes, values: Mapping[str, str]) -> bytes:
    """Populate `.docx` slots (`ff:*`, `sdt:*`, and `cell:*`) across document body,
    headers, and footers from `values`."""
    try:
        zin_ctx = zipfile.ZipFile(io.BytesIO(docx_bytes), "r")
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise ValueError("not a valid .docx archive") from exc
    with zin_ctx as zin:
        _validate_docx_archive(zin)
        parts = _docx_xml_parts(zin)
        part_set = set(parts)
        remaining = _MAX_DOCX_UNCOMPRESSED_BYTES
        part_bytes: dict[str, bytes] = {}
        for p in parts:
            raw_part = _read_zip_member(zin, p, max_bytes=remaining)
            remaining -= len(raw_part)
            part_bytes[p] = raw_part
        other_files: dict[str, tuple[zipfile.ZipInfo, bytes]] = {}
        for info in zin.infolist():
            if info.filename not in part_set:
                raw_other = _read_zip_member(zin, info.filename, max_bytes=remaining)
                remaining -= len(raw_other)
                other_files[info.filename] = (info, raw_other)

    updated_parts: dict[str, bytes] = {}
    ff_idx = 0
    sdt_idx = 0
    seen_ids: dict[str, int] = {}
    for part_name in parts:
        root = _parse_docx_xml(part_bytes[part_name])
        ff_idx, sdt_idx = _fill_part_slots(
            root,
            values,
            part_prefix=_part_prefix(part_name),
            ff_start=ff_idx,
            sdt_start=sdt_idx,
            seen_ids=seen_ids,
        )
        updated_parts[part_name] = tostring(root, encoding="utf-8", xml_declaration=True)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for filename, (info, data) in other_files.items():
            zout.writestr(info, data)
        for part_name, xml_bytes in updated_parts.items():
            zout.writestr(part_name, xml_bytes)
    return out.getvalue()


def fill_docx_repeating_table(
    docx_bytes: bytes,
    *,
    table_index: int = 0,
    rows: Sequence[Sequence[str]],
    header_rows: int = 1,
) -> bytes:
    """Populate a repeating multi-row `.docx` table (e.g. ECTS self-assessment or
    employment history) by cloning the first data row after `header_rows` for each
    entry in `rows` and removing unused blank template rows."""
    if header_rows < 0:
        raise ValueError("header_rows must be >= 0")
    try:
        zin_ctx = zipfile.ZipFile(io.BytesIO(docx_bytes), "r")
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise ValueError("not a valid .docx archive") from exc
    with zin_ctx as zin:
        _validate_docx_archive(zin)
        remaining = _MAX_DOCX_UNCOMPRESSED_BYTES
        doc_xml = _read_zip_member(zin, "word/document.xml", max_bytes=remaining)
        remaining -= len(doc_xml)
        other_files: dict[str, tuple[zipfile.ZipInfo, bytes]] = {}
        for info in zin.infolist():
            if info.filename != "word/document.xml":
                raw_other = _read_zip_member(zin, info.filename, max_bytes=remaining)
                remaining -= len(raw_other)
                other_files[info.filename] = (info, raw_other)

    root = _parse_docx_xml(doc_xml)
    tables = list(root.iter(f"{_W}tbl"))
    if table_index < 0 or table_index >= len(tables):
        raise ValueError(f"table_index {table_index} out of range (found {len(tables)} tables)")
    tbl = tables[table_index]
    existing_rows = tbl.findall(f"{_W}tr")
    if len(existing_rows) <= header_rows:
        raise ValueError(
            f"table {table_index} has {len(existing_rows)} row(s); need at least {header_rows + 1}"
        )

    template_row = copy.deepcopy(existing_rows[header_rows])
    for old_row in existing_rows[header_rows:]:
        tbl.remove(old_row)

    for row_values in rows:
        cloned = copy.deepcopy(template_row)
        fillable_cells = [
            c for c in cloned.findall(f"{_W}tc") if not _is_vmerge_continue(c)
        ]
        for c_idx, cell in enumerate(fillable_cells):
            val = str(row_values[c_idx]) if c_idx < len(row_values) else ""
            _set_cell_or_container_text(cell, val)
        tbl.append(cloned)

    updated_xml = tostring(root, encoding="utf-8", xml_declaration=True)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for filename, (info, data) in other_files.items():
            zout.writestr(info, data)
        zout.writestr("word/document.xml", updated_xml)
    return out.getvalue()

