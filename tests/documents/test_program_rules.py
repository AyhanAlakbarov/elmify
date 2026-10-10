"""`_atomic_keeping_decisions`: the wrapper that keeps DecisionRecord rows
through a page read's rollback (Task 10 review, fix round 1 finding 4).
"""
import pytest
from django.db import DatabaseError, connection
from django.test.utils import CaptureQueriesContext

from apps.documents.program_rules import _atomic_keeping_decisions
from apps.research.decisions import DecisionsUnavailable
from apps.research.models import DecisionRecord

pytestmark = pytest.mark.django_db


def _record(**kw):
    defaults = dict(
        state_digest="s", question_digest="q", decision="D6.slots",
        question_id="0:document", value="cv", confidence=0.9,
        probabilities={}, model="m", provider="typesafe",
    )
    defaults.update(kw)
    return DecisionRecord.objects.create(**defaults)


def test_kept_rows_are_read_back_in_a_deterministic_order():
    """Fix round 1, finding 4: the recovery query is ordered by
    (state_digest, question_digest, model, question_id), never left to
    whatever order the database happens to return."""
    with CaptureQueriesContext(connection):
        with pytest.raises(DecisionsUnavailable):
            with _atomic_keeping_decisions():
                _record(question_id="b")
                _record(question_id="a")
                raise DecisionsUnavailable("boom", kind="failed")
        selects = [
            q["sql"] for q in connection.queries
            if "decisionrecord" in q["sql"].lower() and q["sql"].upper().startswith("SELECT")
        ]
    assert selects, "no SELECT against DecisionRecord was captured"
    order_by = selects[-1].upper()
    assert "ORDER BY" in order_by
    for column in ("state_digest", "question_digest", "model", "question_id"):
        assert column.upper() in order_by


def test_a_database_error_during_reinsert_surfaces_the_original_exception(
    monkeypatch, caplog
):
    """Fix round 1, finding 4: a DatabaseError while re-inserting the kept
    rows must never replace the caller's own decision exception -- callers
    match on ITS type and .kind, not on whatever the database did on the way
    back in."""
    def broken_bulk_create(*args, **kwargs):
        raise DatabaseError("connection reset")

    monkeypatch.setattr(DecisionRecord.objects, "bulk_create", broken_bulk_create)
    with pytest.raises(DecisionsUnavailable) as raised:
        with _atomic_keeping_decisions(source_url="https://official.example/programme"):
            _record()
            raise DecisionsUnavailable("boom", kind="failed")
    assert raised.value.kind == "failed"
    assert "official.example" in caplog.text
