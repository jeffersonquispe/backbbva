"""Docker-only check that OBJECT_STORAGE_SSE_KMS_KEY_ID really encrypts what
ARIA writes: a throwaway MinIO with a static KMS key (MINIO_KMS_SECRET_KEY,
started by `make test-integration-sse-kms`) stands in for KES."""

from __future__ import annotations

import hashlib
import io
import os
import uuid
from collections.abc import Iterator

import pytest

if not os.getenv("OBJECT_STORAGE_ENDPOINT") or not os.getenv(
    "OBJECT_STORAGE_SSE_KMS_KEY_ID"
):
    pytest.skip(
        "Requires a KMS-enabled MinIO (run make test-integration-sse-kms)",
        allow_module_level=True,
    )

from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.object_storage.minio.minio_object_storage_adapter import (
    MinioObjectStorageAdapter,
)

pytestmark = pytest.mark.docker_integration

KEY_ID = os.environ["OBJECT_STORAGE_SSE_KMS_KEY_ID"]


@pytest.fixture
def storage(monkeypatch) -> Iterator[MinioObjectStorageAdapter]:
    monkeypatch.setattr(genai_config, "OBJECT_STORAGE_SSE_KMS_KEY_ID", KEY_ID)
    adapter = MinioObjectStorageAdapter(bucket=f"sse-kms-it-{uuid.uuid4().hex[:12]}")
    yield adapter
    for obj in adapter.list_objects():
        adapter.delete(obj.key)
    adapter._client.delete_bucket(Bucket=adapter._bucket)


def _encryption(storage: MinioObjectStorageAdapter, key: str) -> tuple[str, str]:
    head = storage._client.head_object(Bucket=storage._bucket, Key=key)
    return head.get("ServerSideEncryption", ""), head.get("SSEKMSKeyId", "")


def test_archive_objects_are_stored_with_the_configured_kms_key(storage) -> None:
    content = b'{"alert":{"alert_id":"a-1"},"fraud_label_reviews":[]}\n'
    key = "fraud-history-archive/created_day=2025-10-26/x.jsonl.gz"

    storage.put_bytes(key, content, "application/gzip")

    algorithm, key_id = _encryption(storage, key)
    assert algorithm == "aws:kms"
    assert key_id.endswith(KEY_ID)
    # Transparent decryption keeps the read-back digest check of the archive.
    assert hashlib.sha256(storage.get_bytes(key)).digest() == hashlib.sha256(
        content
    ).digest()


def test_streamed_uploads_are_encrypted_too(storage) -> None:
    key = "audit-log-archive/date=2026-10-27/part.jsonl.gz"

    storage.put_file(key, io.BytesIO(b"x" * 1024), "application/gzip")

    algorithm, key_id = _encryption(storage, key)
    assert algorithm == "aws:kms" and key_id.endswith(KEY_ID)
    assert storage.get_bytes(key) == b"x" * 1024
