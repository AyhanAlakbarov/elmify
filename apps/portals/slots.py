"""Pair a form's upload boxes with the documents the student holds (spec §7).

The model labelled each box (kind, original/translation, which degree) from
its label, heading and context; this module decides, in code, which file goes
where. Anything it cannot decide is a choice put to the student -- never a
guess -- and an unsure box is never filled.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from .learn import DocumentSlot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeldDocument:
    source: Literal["draft", "upload"]
    id: UUID
    filename: str
    kind: str
    variant: Literal["ORIGINAL", "TRANSLATION"]
    download_path: str


@dataclass
class Pairing:
    assigned: list[tuple[DocumentSlot, HeldDocument]] = field(default_factory=list)
    choices: list[tuple[HeldDocument, list[DocumentSlot]]] = field(default_factory=list)
    unplaced: list[HeldDocument] = field(default_factory=list)


def parse_slots(raw: object) -> list[DocumentSlot]:
    """FieldMap.slots as typed slots. A malformed row is skipped, never raised:
    a box we cannot read is a box nothing is attached to."""
    slots: list[DocumentSlot] = []
    for row in raw if isinstance(raw, list) else []:
        try:
            slots.append(DocumentSlot.model_validate(row))
        except ValidationError:
            logger.warning("skipping malformed DocumentSlot row in FieldMap.slots")
            continue
    return slots


def _fits(slot: DocumentSlot, held: HeldDocument, degree_count: int) -> bool:
    if not slot.sure or slot.kind != held.kind:
        return False
    if slot.variant not in ("ANY", held.variant):
        return False
    # A box for a degree the student does not have takes nothing. Degree 1
    # always exists for a student holding a transcript, fact or no fact.
    return slot.degree is None or slot.degree <= max(degree_count, 1)


def pair_slots(slots: list[DocumentSlot], held: list[HeldDocument], degree_count: int) -> Pairing:
    pairing = Pairing()
    taken: set[str] = set()
    for document in held:
        fits = [s for s in slots if s.selector not in taken and _fits(s, document, degree_count)]
        rivals = [d for d in held if any(_fits(s, d, degree_count) for s in fits)]
        if not fits:
            pairing.unplaced.append(document)
        elif len(fits) == 1 and len(rivals) == 1:
            pairing.assigned.append((fits[0], document))
            taken.add(fits[0].selector)
        else:
            pairing.choices.append((document, fits))
    return pairing
