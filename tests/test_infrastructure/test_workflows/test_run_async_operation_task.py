from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationStatus,
)
from src.infrastructure.entrypoint.worker.celery import tasks


class _Repository:
    def __init__(self, operation: AsyncOperationRecord | None) -> None:
        self.operation = operation
        self.updates: list[dict] = []

    def get(self, operation_id):
        return self.operation

    def update(self, operation_id, **changes):
        self.updates.append(changes)
        return self.operation


def _operation(operation_type: str) -> AsyncOperationRecord:
    now = datetime.now(UTC)
    return AsyncOperationRecord(
        id=uuid4(),
        operation_type=operation_type,
        status=AsyncOperationStatus.DISPATCHED,
        payload={},
        result=None,
        error=None,
        created_at=now,
        updated_at=now,
        created_by=None,
    )


def test_run_async_operation_fails_unsupported_type_instead_of_succeeding(monkeypatch):
    operation = _operation("fraud.massive-review")
    repository = _Repository(operation)
    monkeypatch.setattr(tasks, "get_async_operation_repository", lambda: repository)

    result = tasks.run_async_operation(str(operation.id))

    assert result["status"] == "failed"
    assert repository.updates == [
        {
            "status": AsyncOperationStatus.FAILED,
            "error": "Unsupported async operation type: fraud.massive-review",
        }
    ]


def test_run_async_operation_reports_missing_operation(monkeypatch):
    repository = _Repository(None)
    monkeypatch.setattr(tasks, "get_async_operation_repository", lambda: repository)

    result = tasks.run_async_operation(str(uuid4()))

    assert result["status"] == "not_found"
    assert repository.updates == []
