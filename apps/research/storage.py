from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Protocol

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from django.conf import settings


class _StreamingBody(Protocol):
    def read(self) -> bytes: ...


class S3Client(Protocol):
    def put_object(self, **kwargs: object) -> dict[str, str]: ...

    def get_object(self, **kwargs: object) -> dict[str, _StreamingBody]: ...


class S3ObjectStore:
    """Concrete ``ObjectStore`` (see snapshot.py's Protocol) backed by boto3.

    Mirrors apps/research/queue.py's client-construction pattern: a bare
    boto3.client call, no custom retry/session wrapper.
    """

    def __init__(self, *, bucket: str | None = None, client: S3Client | None = None) -> None:
        self._bucket = bucket or settings.EVIDENCE_BUCKET_NAME
        if client is None and settings.DEBUG and self._bucket.startswith("test-"):
            # A developer machine: no S3, so objects live under .local-store/.
            # Production names a real bucket, so this never runs there.
            client = _LocalS3(Path(settings.BASE_DIR) / ".local-store" / self._bucket)
        self._client = client or boto3.client("s3")

    def put(self, key: str, body: bytes) -> str:
        response = self._client.put_object(Bucket=self._bucket, Key=key, Body=body)
        return response.get("VersionId", "null")

    def get(self, key: str) -> bytes:
        """Bytes for ``key``, or ``KeyError`` if absent -- what callers catch.

        Only NoSuchKey translates: reporting "missing" for AccessDenied would
        hide a broken IAM policy. Note S3 *does* answer AccessDenied for an
        absent object when the caller lacks s3:ListBucket.
        """
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") != "NoSuchKey":
                raise
            raise KeyError(key) from error
        return response["Body"].read()

    def get_version(self, key: str, version_id: str) -> bytes:
        """One version of ``key``, never the latest by default: what GuardDuty scanned.

        ``KeyError`` for an absent key or version, like ``get``.
        """
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key, VersionId=version_id)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in ("NoSuchKey", "NoSuchVersion"):
                raise
            raise KeyError(key) from error
        return response["Body"].read()


class _LocalS3:
    """Just enough of an S3 client for a developer machine: put and get by key."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: object) -> Path:
        path = (self._root / str(key)).resolve()
        if not path.is_relative_to(self._root.resolve()):
            raise ValueError("key escapes the local store")
        return path

    def put_object(self, **kwargs: object) -> dict[str, str]:
        path = self._path(kwargs["Key"])
        path.parent.mkdir(parents=True, exist_ok=True)
        body = kwargs["Body"]
        path.write_bytes(body if isinstance(body, bytes) else str(body).encode())
        return {"VersionId": "local"}

    def get_object(self, **kwargs: object) -> dict[str, _StreamingBody]:
        path = self._path(kwargs["Key"])
        if not path.exists():
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": BytesIO(path.read_bytes())}
