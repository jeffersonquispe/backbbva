from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from enum import StrEnum

from src.application.ports.async_operation_port import AsyncOperationRecord


class AsyncExecutionState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AsyncExecutionSnapshot:
    state: AsyncExecutionState
    detail: str | None = None
    result: dict | None = None


class AsyncExecutionInspector(ABC):
    def inspect(
        self,
        operation: AsyncOperationRecord,
    ) -> AsyncExecutionSnapshot:
        raise NotImplementedError
