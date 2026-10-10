import pytest
from pydantic import ValidationError

from apps.research.disciplines import BUCKETS, UNCLASSIFIABLE
from apps.research.models import ProfileCellSelection
from apps.research.profile_cells import BucketReading, select_bucket
from apps.tenancy.context import tenant_scope
from tests.research.conftest import FakeResponse, FakeResponses

pytestmark = pytest.mark.django_db

_BUCKET = "physical_sciences"


def _reader(bucket: str = _BUCKET) -> FakeResponses:
    return FakeResponses(FakeResponse(output_parsed=BucketReading(bucket=bucket)))


def test_the_fixture_bucket_is_a_real_bucket() -> None:
    assert _BUCKET in BUCKETS


def test_the_bucket_is_read_once_per_profile_version(student_profile_version) -> None:
    reader = _reader()
    with tenant_scope(student_profile_version.tenant_id):
        first = select_bucket(student_profile_version, parser=reader)
        second = select_bucket(student_profile_version, parser=reader)
        assert ProfileCellSelection.objects.count() == 1
        row = ProfileCellSelection.objects.get()
    assert first == second == _BUCKET
    assert len(reader.calls) == 1
    assert row.student_id == student_profile_version.student_id
    assert row.discipline_bucket == _BUCKET


def test_only_the_field_words_reach_the_model(student_profile_version) -> None:
    reader = _reader()
    with tenant_scope(student_profile_version.tenant_id):
        select_bucket(student_profile_version, parser=reader)
    call = reader.calls[0]
    sent = str(call["input"])
    snapshot = student_profile_version.snapshot
    assert snapshot["target_field"] in sent and "catalysis" in sent
    for never in (
        "nationality", "date_of_birth", "application_budget", "Example University",
        snapshot["date_of_birth"],
    ):
        assert never not in sent
    assert call["store"] is False
    assert call["max_output_tokens"] <= 64
    assert call["safety_identifier"] != str(student_profile_version.student_id)
    assert "DATA" in sent


def test_the_answer_schema_is_closed_over_the_buckets() -> None:
    with pytest.raises(ValidationError):
        BucketReading.model_validate({"bucket": "astrology"})
    with pytest.raises(ValidationError):
        BucketReading.model_validate({"bucket": _BUCKET, "why": "extra"})


def test_rate_limited_returns_unclassifiable_and_stores_nothing(
    student_profile_version, monkeypatch
) -> None:
    monkeypatch.setattr("apps.research.profile_cells.rate_limited", lambda *a, **k: True)
    reader = _reader()
    with tenant_scope(student_profile_version.tenant_id):
        assert select_bucket(student_profile_version, parser=reader) == UNCLASSIFIABLE
        assert not ProfileCellSelection.objects.exists()
    assert reader.calls == []


class _OffSchema:
    """Both SDKs raise ValidationError inside parse() on an off-schema answer."""

    def __init__(self) -> None:
        self.calls = 0

    def parse(self, **kwargs: object) -> object:
        self.calls += 1
        BucketReading.model_validate({"bucket": "astrology"})
        raise AssertionError("unreachable")


def test_an_off_schema_answer_is_unclassifiable_and_stores_nothing(
    student_profile_version,
) -> None:
    reader = _OffSchema()
    with tenant_scope(student_profile_version.tenant_id):
        assert select_bucket(student_profile_version, parser=reader) == UNCLASSIFIABLE
        assert not ProfileCellSelection.objects.exists()
        # Nothing was cached, so the next call asks again.
        assert select_bucket(student_profile_version, parser=_reader()) == _BUCKET
    assert reader.calls == 1


def test_a_refusal_is_unclassifiable_and_stores_nothing(student_profile_version) -> None:
    reader = FakeResponses(FakeResponse(output_parsed=None))
    with tenant_scope(student_profile_version.tenant_id):
        assert select_bucket(student_profile_version, parser=reader) == UNCLASSIFIABLE
        assert not ProfileCellSelection.objects.exists()
