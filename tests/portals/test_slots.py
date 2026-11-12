"""Which held document goes in which upload box (spec §7). Pure code, no model:
the model only labelled the boxes (Task 4 learning); pairing is decided here,
and anything code cannot decide is the student's choice, never a guess."""

from uuid import uuid4

from apps.portals.learn import DocumentSlot
from apps.portals.slots import HeldDocument, pair_slots, parse_slots


def _held(kind: str, variant: str = "ORIGINAL", name: str = "") -> HeldDocument:
    return HeldDocument(source="upload", id=uuid4(), filename=name or f"{kind.lower()}.pdf",
                        kind=kind, variant=variant, download_path="/ext/documents/x")


def _slot(selector: str, kind: str, variant: str = "ANY", degree: int | None = None,
          sure: bool = True) -> DocumentSlot:
    return DocumentSlot(selector=selector, kind=kind, variant=variant, degree=degree, sure=sure)


def test_original_and_translation_each_go_to_their_own_box() -> None:
    original, english = _held("TRANSCRIPT"), _held("TRANSCRIPT", "TRANSLATION")
    pairing = pair_slots(
        [_slot("#t1o", "TRANSCRIPT", "ORIGINAL", 1), _slot("#t1e", "TRANSCRIPT", "TRANSLATION", 1)],
        [original, english], degree_count=1,
    )
    assert {s.selector: d for s, d in pairing.assigned} == {"#t1o": original, "#t1e": english}
    assert pairing.choices == [] and pairing.unplaced == []


def test_a_second_degree_box_gets_nothing_for_a_one_degree_student() -> None:
    pairing = pair_slots(
        [_slot("#t1o", "TRANSCRIPT", "ORIGINAL", 1), _slot("#t2o", "TRANSCRIPT", "ORIGINAL", 2)],
        [_held("TRANSCRIPT")], degree_count=1,
    )
    assert [s.selector for s, _ in pairing.assigned] == ["#t1o"]


def test_a_first_degree_box_takes_a_transcript_with_no_education_fact() -> None:
    pairing = pair_slots([_slot("#t1o", "TRANSCRIPT", "ORIGINAL", 1)], [_held("TRANSCRIPT")], 0)
    assert [s.selector for s, _ in pairing.assigned] == ["#t1o"]


def test_two_originals_for_two_degree_boxes_is_the_students_choice() -> None:
    a, b = _held("TRANSCRIPT", name="bsc.pdf"), _held("TRANSCRIPT", name="msc.pdf")
    pairing = pair_slots(
        [_slot("#t1o", "TRANSCRIPT", "ORIGINAL", 1), _slot("#t2o", "TRANSCRIPT", "ORIGINAL", 2)],
        [a, b], degree_count=2,
    )
    assert pairing.assigned == []
    assert sorted(d.filename for d, _ in pairing.choices) == ["bsc.pdf", "msc.pdf"]
    assert all(len(options) == 2 for _, options in pairing.choices)


def test_an_unsure_slot_is_never_assigned() -> None:
    cv = _held("CV")
    pairing = pair_slots([_slot("#up", "CV", sure=False)], [cv], degree_count=1)
    assert pairing.assigned == [] and pairing.unplaced == [cv]


def test_a_document_with_no_slot_is_unplaced() -> None:
    passport = _held("PASSPORT")
    assert pair_slots([_slot("#cv", "CV")], [passport], degree_count=1).unplaced == [passport]


def test_a_malformed_stored_slot_is_skipped_not_raised() -> None:
    good = {"selector": "#cv", "kind": "CV", "variant": "ANY", "degree": None, "sure": True}
    assert [s.selector for s in parse_slots([good, {"selector": "#x"}, "junk"])] == ["#cv"]
