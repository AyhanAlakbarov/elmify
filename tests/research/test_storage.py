"""S3ObjectStore.get's failure contract.

download_document catches KeyError; the real store used to leak botocore's
ClientError, so a missing artefact 500'd instead of 404'ing. The dict-backed
test doubles raised KeyError all along, which is why nothing caught it.
"""

import io

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from apps.research.storage import S3ObjectStore


class _FakeS3Client:
    def __init__(self, *, error_code: str | None = None) -> None:
        self._error_code = error_code

    def get_object(self, **kwargs: object) -> dict[str, object]:
        if self._error_code is not None:
            raise ClientError({"Error": {"Code": self._error_code}}, "GetObject")
        return {"Body": io.BytesIO(b"%PDF-1.4")}


def _store(error_code: str | None = None) -> S3ObjectStore:
    return S3ObjectStore(bucket="b", client=_FakeS3Client(error_code=error_code))  # type: ignore[arg-type]


def test_a_missing_object_raises_key_error():
    with pytest.raises(KeyError):
        _store("NoSuchKey").get("gone.pdf")


def test_access_denied_is_not_reported_as_missing():
    """Answering 'missing' for a permissions problem would turn a broken IAM
    policy into a silent 404 for every student."""
    with pytest.raises(ClientError):
        _store("AccessDenied").get("some.pdf")
