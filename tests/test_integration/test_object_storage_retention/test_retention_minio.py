"""Docker-only e2e of the retention sweep against the real MinIO service:
JSON rules -> parsed rules -> use case -> S3 list/delete on a throwaway bucket.

MinIO stamps ``LastModified`` itself, so age is simulated by moving the
clock forward instead of back-dating objects."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

if not os.getenv("OBJECT_STORAGE_ENDPOINT"):
    pytest.skip(
        "Requires MinIO (set OBJECT_STORAGE_ENDPOINT, e.g. http://localhost:9000)",
        allow_module_level=True,
    )

from src.application.ports.clock_port import Clock
from src.application.use_cases.object_storage.apply_retention import (
    ApplyObjectStorageRetentionUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.object_storage.minio.minio_object_storage_adapter import (
    MinioObjectStorageAdapter,
)
from src.infrastructure.workflows.celery import task_factories

pytestmark = pytest.mark.docker_integration


class OffsetClock(Clock):
    def __init__(self, days: int) -> None:
        self._offset = timedelta(days=days)

    def now(self) -> datetime:
        return datetime.now(UTC) + self._offset


@pytest.fixture
def storage() -> Iterator[MinioObjectStorageAdapter]:
    adapter = MinioObjectStorageAdapter(bucket=f"retention-e2e-{uuid.uuid4().hex[:12]}")
    yield adapter
    for obj in adapter.list_objects():
        adapter.delete(obj.key)
    adapter._client.delete_bucket(Bucket=adapter._bucket)


def _seed(storage: MinioObjectStorageAdapter) -> None:
    storage.put_text("alerts/1/raw-payload.json", "{}", "application/json")
    storage.put_text("alerts/2/agent-output.json", "{}", "application/json")
    storage.put_text("audit/keep.json", "{}", "application/json")


def _keys(storage: MinioObjectStorageAdapter) -> set[str]:
    return {obj.key for obj in storage.list_objects()}


def _rules(monkeypatch, *rules: dict) -> list:
    monkeypatch.setattr(
        genai_config, "OBJECT_STORAGE_RETENTION_RULES", json.dumps(list(rules))
    )
    return task_factories.get_object_storage_retention_rules()


def test_list_objects_reports_prefix_size_and_timestamp(storage) -> None:
    _seed(storage)

    listed = storage.list_objects("alerts/")

    assert sorted(o.key for o in listed) == [
        "alerts/1/raw-payload.json",
        "alerts/2/agent-output.json",
    ]
    assert all(o.size == 2 for o in listed)
    assert all(
        abs(datetime.now(UTC) - o.last_modified) < timedelta(minutes=5) for o in listed
    )


def test_expired_objects_are_deleted_and_other_prefixes_survive(
    storage, monkeypatch
) -> None:
    _seed(storage)
    rules = _rules(
        monkeypatch, {"store": "reports", "prefix": "alerts/", "max_age_days": 30}
    )
    use_case = ApplyObjectStorageRetentionUseCase(
        {"reports": storage}, OffsetClock(days=31)
    )

    out = use_case.execute(rules, dry_run=False)

    assert out.deleted == 2
    assert _keys(storage) == {"audit/keep.json"}


def test_objects_younger_than_the_window_are_kept(storage, monkeypatch) -> None:
    _seed(storage)
    rules = _rules(
        monkeypatch, {"store": "reports", "prefix": "alerts/", "max_age_days": 30}
    )
    use_case = ApplyObjectStorageRetentionUseCase(
        {"reports": storage}, OffsetClock(days=29)
    )

    out = use_case.execute(rules, dry_run=False)

    assert out.deleted == 0
    assert len(_keys(storage)) == 3


def test_dry_run_matches_but_never_deletes(storage, monkeypatch) -> None:
    _seed(storage)
    rules = _rules(
        monkeypatch, {"store": "reports", "prefix": "alerts/", "max_age_days": 1}
    )
    use_case = ApplyObjectStorageRetentionUseCase(
        {"reports": storage}, OffsetClock(days=10)
    )

    out = use_case.execute(rules, dry_run=True)

    assert out.results[0].matched == 2
    assert out.deleted == 0
    assert len(_keys(storage)) == 3
