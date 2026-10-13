from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from src.application.ports.async_operation_port import AsyncOperationRecord


@dataclass(frozen=True)
class AsyncExecutionRef:
    backend: str
    external_id: str | None = None


class AsyncExecutor(ABC):
    def dispatch(self, operation: AsyncOperationRecord) -> AsyncExecutionRef:
        raise NotImplementedError
