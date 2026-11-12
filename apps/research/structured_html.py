"""Rung 0 structured JSON-LD extractor and 2D HTML table / definition-list AST normalizer.

Solves two structural gaps in flattened line-by-line page reading:
1. `<script type="application/ld+json">` (`Course`, `EducationalOccupationalProgram`,
   `MonetaryGrant`, `Offer`) often holds clean structured tuition, duration, language, and
   deadline fields, which `_CHROME` stripping previously discarded. Every value extracted here
   is cross-checked for a byte-exact substring match in the visible HTML text so no hidden or
   spoofed `<script>` value can enter a `Section` without appearing visibly on the page.
2. Flattening `<tr>` into `| cell1 | cell2 |` loses the 2D coordinate binding between a cell's
   row header (e.g. `Non-EU/EEA Students` or `Category B`) and its column header (e.g.
   `Tuition per Academic Year` or `Application Deadline`). `extract_html_lines_with_coordinates`
   binds each table cell to `header=f"{row_header} | {col_header}"` and each `<dl>` `<dd>` to
   its `<dt>` term, while keeping `line.text` as the verbatim cell text so `locate()` matches
   byte for byte.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import lxml.html
from lxml.etree import Comment, ParserError, strip_elements

from apps.research.candidates import Line

_CHROME_NO_SCRIPT = ("style", "noscript", "nav", "header", "footer", "form", "svg")
_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_MAX_CELL_CHARS = 300
_VALUE_CELL_RE = re.compile(
    r"(?:€|\$|£|¥|₩|₺|₼|₽|₹|\b(?:EUR|USD|GBP|CHF|SEK|NOK|DKK|PLN|CZK|HUF|"
    r"CAD|AUD|NZD|JPY|KRW|CNY|SGD|AED|SAR|QAR|KWD|BHD|TRY|AZN|RUB|INR)\b)"
    r"|^\s*\d+(?:[.,/]\d+)*(?:\s*%)?\s*$"
    r"|\b\d+\s*(?:ects|credits?|years?|months?|semesters?|weeks?|hours?|days?|pages?|mb)\b"
    r"|\b(?:ielts|toefl|cefr|gpa|gre|gmat|c1|c2|b2)\b"
    r"|\b(?:english|german|french|italian|spanish|dutch|korean|japanese|chinese|arabic|"
    r"full[- ]?time|part[- ]?time|on[- ]?campus|online|blended|"
    r"m\.?sc\.?|m\.?a\.?|b\.?sc\.?|b\.?a\.?|ph\.?d\.?|ll\.?m\.?|mba|"
    r"yes|no|required|optional|mandatory|europass)\b",
    re.IGNORECASE,
)
_CURRENCY_SYMBOLS: dict[str, str] = {
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
    "JPY": "¥",
    "KRW": "₩",
    "TRY": "₺",
    "AZN": "₼",
    "RUB": "₽",
    "INR": "₹",
}
_DIMENSION_COL_RE = re.compile(
    r"\b(?:category|band|tier|tariff|group|nationality|citizenship|residence|status|"
    r"audience|origin|region|level|degree|track|stream|mode|format|programme|program)\b",
    re.IGNORECASE,
)
_CURRENCY_IN_CELL_RE = re.compile(
    r"(?:€|\$|£|¥|₩|₺|₼|₽|₹|\b(?:EUR|USD|GBP|CHF|SEK|NOK|DKK|PLN|CZK|HUF|"
    r"CAD|AUD|NZD|JPY|KRW|CNY|SGD|AED|SAR|QAR|KWD|BHD|TRY|AZN|RUB|INR)\b)",
    re.IGNORECASE,
)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_doc(html: bytes | str) -> lxml.html.HtmlElement | None:
    raw = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    if not raw or not raw.strip():
        return None
    try:
        return lxml.html.fromstring(raw)
    except (ParserError, ValueError):
        return None


def _iter_jsonld_nodes(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        out.append(payload)
        for val in payload.values():
            if isinstance(val, (dict, list)):
                out.extend(_iter_jsonld_nodes(val))
    elif isinstance(payload, list):
        for item in payload:
            out.extend(_iter_jsonld_nodes(item))
    return out


def _match_money_in_visible(amount_str: str, currency: str, visible_text: str) -> str:
    """Return the first verbatim currency+amount representation of `(amount_str, currency)`
    that appears in `visible_text`, handling thousands separators (`,`, `.`, ` `) and symbols."""
    raw_num = amount_str.strip()
    curr = currency.strip().upper()
    if not raw_num or not curr:
        return ""
    num_variants: list[str] = [raw_num]
    # Strip trailing .00 / .0 if integer
    int_str = re.sub(r"\.0+$", "", raw_num)
    if int_str not in num_variants:
        num_variants.append(int_str)
    if int_str.isdigit() and len(int_str) >= 4:
        val_int = int(int_str)
        comma_fmt = f"{val_int:,}"
        dot_fmt = comma_fmt.replace(",", ".")
        space_fmt = comma_fmt.replace(",", " ")
        for fmt in (comma_fmt, dot_fmt, space_fmt):
            if fmt not in num_variants:
                num_variants.append(fmt)

    curr_tokens: list[str] = [currency.strip()]
    sym = _CURRENCY_SYMBOLS.get(curr)
    if sym and sym not in curr_tokens:
        curr_tokens.append(sym)

    for c_tok in curr_tokens:
        for n_str in num_variants:
            for candidate in (f"{c_tok} {n_str}", f"{c_tok}{n_str}", f"{n_str} {c_tok}"):
                if candidate in visible_text:
                    return candidate
    return ""


def extract_jsonld_lines(html: bytes | str) -> tuple[Line, ...]:
    """Extract structured facts from `application/ld+json` blocks whose values also appear
    verbatim in the visible page text (so `locate()` and byte-exact provenance hold)."""
    doc = _parse_doc(html)
    if doc is None:
        return ()

    scripts = [
        s.text_content()
        for s in doc.xpath("//script[@type='application/ld+json']")
        if s.text_content() and s.text_content().strip()
    ]
    if not scripts:
        return ()

    strip_elements(doc, "script", *_CHROME_NO_SCRIPT, Comment, with_tail=False)
    visible_text = _collapse(str(doc.text_content()))
    if not visible_text:
        return ()

    lines: list[Line] = []
    seen: set[tuple[str, str]] = set()

    def _add_if_visible(label: str, value_str: str, heading: str) -> None:
        cleaned = _collapse(value_str)
        if len(cleaned) < 2 or len(cleaned) > _MAX_CELL_CHARS:
            return
        if cleaned not in visible_text:
            return
        key = (label, cleaned)
        if key in seen:
            return
        seen.add(key)
        lines.append(Line(text=cleaned, heading=heading[:160], header=label[:160]))

    for raw_script in scripts:
        try:
            parsed = json.loads(raw_script)
        except (ValueError, TypeError):
            continue
        for node in _iter_jsonld_nodes(parsed):
            node_type = str(node.get("@type", ""))
            heading = _collapse(str(node.get("name", ""))) or node_type or "Structured Data"
            for field_key, header_label in (
                ("timeToComplete", "Schema.org Duration"),
                ("educationalCredentialAwarded", "Schema.org Degree"),
                ("inLanguage", "Schema.org Teaching Language"),
                ("applicationDeadline", "Schema.org Application Deadline"),
                ("startDate", "Schema.org Start Date"),
                ("educationalProgramMode", "Schema.org Study Mode"),
            ):
                val = node.get(field_key)
                if isinstance(val, str):
                    _add_if_visible(header_label, val, heading)
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, str):
                            _add_if_visible(header_label, item, heading)

            offers = node.get("offers")
            offer_list = (
                offers
                if isinstance(offers, list)
                else ([offers] if isinstance(offers, dict) else [])
            )
            for offer in offer_list:
                if not isinstance(offer, dict):
                    continue
                cat = _collapse(str(offer.get("category") or offer.get("name") or "Tuition Offer"))
                price = str(offer.get("price", "")).strip()
                currency = str(offer.get("priceCurrency", "")).strip()
                if price and currency:
                    matched_offer = _match_money_in_visible(price, currency, visible_text)
                    if matched_offer:
                        _add_if_visible(f"Schema.org Offer | {cat}", matched_offer, heading)

            amounts = node.get("amount") or node.get("funder")
            amount_list = (
                amounts
                if isinstance(amounts, list)
                else ([amounts] if isinstance(amounts, dict) else [])
            )
            for amt in amount_list:
                if not isinstance(amt, dict):
                    continue
                val_str = str(amt.get("value") or amt.get("maxValue") or "").strip()
                currency = str(amt.get("currency", "")).strip()
                if val_str and currency:
                    matched_amt = _match_money_in_visible(val_str, currency, visible_text)
                    if matched_amt:
                        _add_if_visible("Schema.org Grant Amount", matched_amt, heading)

    return tuple(lines)


def _iter_tagged_blocks(
    html: bytes | str, tags: frozenset[str]
) -> Iterator[tuple[str, lxml.html.HtmlElement, str]]:
    doc = _parse_doc(html)
    if doc is None:
        return
    strip_elements(doc, "script", *_CHROME_NO_SCRIPT, Comment, with_tail=False)
    current_heading = ""
    for elem in doc.iter():
        if not isinstance(elem.tag, str):
            continue
        tag = elem.tag.lower()
        if tag in _HEADINGS:
            if h_text := _collapse(str(elem.text_content())):
                current_heading = h_text
        elif tag in tags:
            yield tag, elem, current_heading


def extract_table_groups(html: bytes | str) -> tuple[tuple[Line, ...], ...]:
    """Extract 2D coordinate-bound lines grouped per `<table>` element in document order."""
    return tuple(
        tuple(tbl_lines)
        for _, elem, heading in _iter_tagged_blocks(html, frozenset({"table"}))
        if (tbl_lines := _extract_single_table(elem, heading))
    )


def extract_dl_lines(html: bytes | str) -> tuple[Line, ...]:
    """Extract coordinate-bound lines from HTML `<dl>` (`<dt>`/`<dd>`) elements."""
    return tuple(
        line
        for _, elem, heading in _iter_tagged_blocks(html, frozenset({"dl"}))
        for line in _extract_single_dl(elem, heading)
    )


def extract_table_and_dl_lines(html: bytes | str) -> tuple[Line, ...]:
    """Extract 2D coordinate-bound lines from HTML `<table>` and `<dl>` elements."""
    out: list[Line] = []
    for tag, elem, heading in _iter_tagged_blocks(html, frozenset({"table", "dl"})):
        if tag == "table":
            out.extend(_extract_single_table(elem, heading))
        else:
            out.extend(_extract_single_dl(elem, heading))
    return tuple(out)


def _expand_table_grid(
    rows: list[lxml.html.HtmlElement],
) -> list[tuple[lxml.html.HtmlElement, list[tuple[str, str]]]]:
    """Expand `rowspan`/`colspan` into aligned `(row_elem, [(tag, text), ...])` rows."""
    expanded: list[tuple[lxml.html.HtmlElement, list[tuple[str, str]]]] = []
    # active_spans[col_idx] = (remaining_rows, tag, text)
    active_spans: dict[int, tuple[int, str, str]] = {}

    for row in rows:
        cells = row.xpath("./th | ./td")
        if not cells and not active_spans:
            continue
        row_cells: list[tuple[str, str]] = []
        col_idx = 0

        def _consume_active(c_idx: int) -> int:
            while c_idx in active_spans:
                rem, s_tag, s_text = active_spans.pop(c_idx)
                row_cells.append((s_tag, s_text))
                if rem > 1:
                    active_spans[c_idx] = (rem - 1, s_tag, s_text)
                c_idx += 1
            return c_idx

        col_idx = _consume_active(col_idx)
        for cell in cells:
            col_idx = _consume_active(col_idx)
            tag = cell.tag.lower() if isinstance(cell.tag, str) else "td"
            # Skip cells that wrap a nested `<table>`: `doc.iter()` visits the inner table directly
            if cell.xpath(".//table"):
                text = ""
            else:
                text = _collapse(str(cell.text_content()))
            try:
                colspan = max(1, min(12, int(cell.get("colspan") or 1)))
            except ValueError:
                colspan = 1
            try:
                rowspan = max(1, min(20, int(cell.get("rowspan") or 1)))
            except ValueError:
                rowspan = 1
            for _ in range(colspan):
                row_cells.append((tag, text))
                if rowspan > 1:
                    active_spans[col_idx] = (rowspan - 1, tag, text)
                col_idx += 1
        _consume_active(col_idx)
        expanded.append((row, row_cells))
    return expanded


def _is_column_header_row(
    row: lxml.html.HtmlElement,
    tags: list[str],
    texts: list[str],
    *,
    total_rows: int,
    has_col_headers: bool,
    seen_data_row: bool,
) -> bool:
    """Return True when `row` is a table column-header row rather than a key-value data row."""
    # Allow empty `<td></td>` top-left corner cells when all non-empty cells are `<th>`
    all_non_empty_th = any(texts) and all(
        t == "th" for t, txt in zip(tags, texts, strict=False) if txt
    )
    if all_non_empty_th or bool(row.xpath("parent::thead")):
        return True
    if has_col_headers or seen_data_row or total_rows <= 1:
        return False
    # `<tr><th>Key</th><td>Value</td></tr>` is a horizontal key-value row, never column headers.
    if tags[0] == "th" and any(t == "td" for t in tags[1:]):
        return False
    # If any cell after column 0 already carries a number, currency, degree, or language value,
    # row 0 is a key-value data row (e.g. `<tr><td>Tuition</td><td>EUR 15,000</td></tr>`).
    if any(_VALUE_CELL_RE.search(cell) for cell in texts[1:] if cell):
        return False
    return all(len(cell) <= 60 for cell in texts if cell)


def _extract_single_table(table: lxml.html.HtmlElement, section_heading: str) -> list[Line]:
    caption_nodes = table.xpath("./caption")
    caption = _collapse(str(caption_nodes[0].text_content())) if caption_nodes else ""

    raw_rows = table.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr")
    if not raw_rows:
        return []

    grid = _expand_table_grid(raw_rows)
    if not grid:
        return []

    col_headers: list[str] = []
    group_banner = ""
    seen_data_row = False
    lines: list[Line] = []

    for row, row_cells in grid:
        tags = [t for t, _ in row_cells]
        texts = [txt for _, txt in row_cells]
        if not any(texts):
            continue

        unique_non_empty = {txt for txt in texts if txt}
        raw_cells = row.xpath("./th | ./td")
        # Single-cell spanning banner row (e.g., <tr colspan="3"><td>Non-EU Citizens</td></tr>)
        if len(unique_non_empty) == 1 and len(raw_cells) == 1 and (
            raw_cells[0].get("colspan") or tags[0] == "th"
        ):
            group_banner = next(iter(unique_non_empty))
            continue

        if _is_column_header_row(
            row,
            tags,
            texts,
            total_rows=len(grid),
            has_col_headers=bool(col_headers),
            seen_data_row=seen_data_row,
        ):
            if not col_headers:
                col_headers = texts
            else:
                max_len = max(len(col_headers), len(texts))
                merged_headers: list[str] = []
                for idx in range(max_len):
                    prev_h = col_headers[idx] if idx < len(col_headers) else ""
                    curr_h = texts[idx] if idx < len(texts) else ""
                    if prev_h and curr_h and prev_h.lower() != curr_h.lower():
                        merged_headers.append(f"{prev_h} ({curr_h})")
                    else:
                        merged_headers.append(curr_h or prev_h)
                col_headers = merged_headers
            continue

        seen_data_row = True

        base_row_header = texts[0]
        if (
            base_row_header
            and len(base_row_header) <= 4
            and col_headers
            and col_headers[0]
            and col_headers[0].lower() not in base_row_header.lower()
        ):
            base_row_header = f"{col_headers[0]} {base_row_header}"
        if group_banner and group_banner.lower() not in base_row_header.lower():
            base_row_header = (
                f"{group_banner}: {base_row_header}" if base_row_header else group_banner
            )

        for col_idx, cell_text in enumerate(texts):
            if not cell_text or len(cell_text) > _MAX_CELL_CHARS:
                continue
            if col_idx == 0 and len(texts) > 1:
                continue
            # Include intermediate dimension columns (e.g. Citizenship / Category / Level in col 1)
            row_qualifiers: list[str] = [base_row_header] if base_row_header else []
            for prev_idx in range(1, col_idx):
                prev_txt = texts[prev_idx]
                if not prev_txt or prev_txt == cell_text or prev_txt in row_qualifiers:
                    continue
                prev_col_hdr = col_headers[prev_idx] if prev_idx < len(col_headers) else ""
                is_dim = (
                    tags[prev_idx] == "th"
                    or bool(_DIMENSION_COL_RE.search(prev_col_hdr))
                ) and not _CURRENCY_IN_CELL_RE.search(prev_txt)
                if is_dim:
                    row_qualifiers.append(prev_txt)

            row_header = " | ".join(row_qualifiers)
            col_header = col_headers[col_idx] if col_idx < len(col_headers) else ""
            header_parts = [p for p in (caption, row_header, col_header) if p and p != cell_text]
            coord_header = " | ".join(header_parts)
            lines.append(
                Line(
                    text=cell_text,
                    heading=section_heading[:160],
                    header=coord_header[:200],
                )
            )
    return lines


def _extract_single_dl(dl: lxml.html.HtmlElement, section_heading: str) -> list[Line]:
    lines: list[Line] = []
    current_dt = ""
    for child in dl.xpath("./dt | ./dd | ./div/*[self::dt or self::dd]"):
        tag = child.tag.lower()
        text = _collapse(str(child.text_content()))
        if not text:
            continue
        if tag == "dt":
            current_dt = text
        elif tag == "dd" and len(text) <= _MAX_CELL_CHARS:
            lines.append(
                Line(
                    text=text,
                    heading=section_heading[:160],
                    header=current_dt[:200],
                )
            )
    return lines
