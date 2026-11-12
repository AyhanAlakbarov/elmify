"""Data models, slot specifications, and inspection results for form filling."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from anyascii import anyascii

_TRUTHY_CHECKBOX = frozenset(
    {
        "true",
        "1",
        "yes",
        "y",
        "on",
        "checked",
        "x",
        "☒",
        "☑",
        "ja",
        "oui",
        "si",
        "sí",
        "evet",
        "bəli",
        "beli",
        "да",
    }
)
_FALSY_CHECKBOX = frozenset(
    {
        "false",
        "0",
        "no",
        "n",
        "off",
        "unchecked",
        "",
        "☐",
        "nein",
        "non",
        "nee",
        "hayır",
        "hayir",
        "xeyr",
        "нет",
    }
)

_GENERIC_PLACEHOLDERS = frozenset(
    {
        "insert text response here",
        "click to enter text",
        "click or tap here to enter text",
        "choose an item.",
        "choose one",
        "choose item",
        "placeholder",
        "klicken oder tippen sie hier, um text einzugeben.",
        "klicken sie hier, um text einzugeben.",
        "wählen sie ein element aus.",
        "cliquez ou appuyez ici pour entrer du texte.",
        "choisissez un élément.",
        "haga clic o pulse aquí para escribir texto.",
        "elija un elemento.",
        "metin girmek için buraya tıklayın veya dokunun.",
        "bir öğe seçin.",
    }
)


def _norm_label_key(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold(), flags=re.UNICODE).strip()


def _ascii_label_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", anyascii(text).casefold()).strip()


def _parse_checkbox_bool(raw: str) -> bool:
    norm = raw.strip().casefold()
    if norm in _TRUTHY_CHECKBOX:
        return True
    if norm in _FALSY_CHECKBOX:
        return False
    raise ValueError(f"invalid checkbox value: {raw!r}")


def _match_dropdown_option(
    value: str,
    options: Sequence[str],
    *,
    allow_custom: bool = False,
) -> tuple[int, str]:
    clean = value.strip()
    for idx, opt in enumerate(options):
        if opt == clean:
            return idx, opt
    for idx, opt in enumerate(options):
        if opt.casefold() == clean.casefold():
            return idx, opt
    if allow_custom:
        return -1, clean
    raise ValueError(f"value {value!r} is not in allowed dropdown options {tuple(options)!r}")


SlotKind = Literal[
    "docx_formtext",
    "docx_checkbox",
    "docx_dropdown",
    "docx_sdt",
    "docx_table_cell",
    "pdf_text",
    "pdf_checkbox",
    "pdf_dropdown",
]
PdfFormKind = Literal["acroform", "xfa", "flat_text", "scanned_image"]


class UnsupportedFormFormat(ValueError):
    """Raised when a form cannot be filled deterministically in place (e.g. XFA PDF)."""


@dataclass(frozen=True)
class FormSlot:
    slot_id: str
    kind: SlotKind
    label: str
    current_value: str = ""
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class PdfFormInspection:
    slots: tuple[FormSlot, ...]
    is_xfa: bool = False
    pdf_kind: PdfFormKind = "acroform"


@dataclass(frozen=True)
class FormFillResult:
    mode: Literal["docx_filled", "pdf_filled", "field_mapped_fallback"]
    filled_bytes: bytes | None
    field_mapped: dict[str, str]
    slots: tuple[FormSlot, ...]
    fallback_reason: str = ""
