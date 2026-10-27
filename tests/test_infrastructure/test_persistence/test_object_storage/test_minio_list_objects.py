from __future__ import annotations

import io
from datetime import UTC, datetime

from src.infrastructure.persistence.object_storage.minio.minio_object_storage_adapter import (
    MinioObjectStorageAdapter,
)

WHEN = datetime(2026, 1, 1, tzinfo=UTC)


class InMemoryS3Paginator:
    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages
        self.calls: list[dict] = []

    def paginate(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self._pages)


class InMemoryS3Client:
    def __init__(self, pages: list[dict]) -> None:
        self.paginator = InMemoryS3Paginator(pages)

    def get_paginator(self, name: str) -> InMemoryS3Paginator:
        assert name == "list_objects_v2"
        return self.paginator


def _adapter(pages: list[dict]) -> tuple[MinioObjectStorageAdapter, InMemoryS3Client]:
    # Skip __init__: it would open a real boto3 client and head the bucket.
    adapter = MinioObjectStorageAdapter.__new__(MinioObjectStorageAdapter)
    client = InMemoryS3Client(pages)
    adapter._bucket = "reports"
    adapter._client = client
    return adapter, client


def test_list_objects_maps_every_page_with_size_and_last_modified() -> None:
    adapter, client = _adapter(
        [
            {"Contents": [{"Key": "alerts/a.json", "Size": 3, "LastModified": WHEN}]},
            {},  # an empty page has no "Contents" key
            {"Contents": [{"Key": "alerts/b.json", "Size": 7, "LastModified": WHEN}]},
        ]
    )

    objects = adapter.list_objects("alerts/")

    assert [(o.key, o.size, o.last_modified) for o in objects] == [
        ("alerts/a.json", 3, WHEN),
        ("alerts/b.json", 7, WHEN),
    ]
    assert client.paginator.calls == [{"Bucket": "reports", "Prefix": "alerts/"}]


class RecordingS3PutClient:
    def __init__(self) -> None:
        self.puts: list[dict] = []
        self.uploads: list[dict] = []

    def put_object(self, **kwargs) -> None:
        self.puts.append(kwargs)

    def upload_fileobj(self, **kwargs) -> None:
        self.uploads.append(kwargs)


def _writer(encryption: dict[str, str]) -> tuple[MinioObjectStorageAdapter, RecordingS3PutClient]:
    adapter = MinioObjectStorageAdapter.__new__(MinioObjectStorageAdapter)
    client = RecordingS3PutClient()
    adapter._bucket = "reports"
    adapter._client = client
    adapter._encryption = encryption
    return adapter, client


def test_writes_request_sse_kms_when_a_key_is_configured() -> None:
    sse = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": "aria-archive"}
    adapter, client = _writer(sse)

    adapter.put_bytes("fraud-history-archive/a.jsonl.gz", b"x", "application/gzip")
    adapter.put_file("datasets/a.csv", io.BytesIO(b"x"), "text/csv")

    assert client.puts[0]["ServerSideEncryption"] == "aws:kms"
    assert client.puts[0]["SSEKMSKeyId"] == "aria-archive"
    assert client.uploads[0]["ExtraArgs"] == {"ContentType": "text/csv", **sse}


def test_writes_carry_no_encryption_header_without_a_key() -> None:
    adapter, client = _writer({})

    adapter.put_bytes("reports/a.json", b"x")

    assert "ServerSideEncryption" not in client.puts[0]
