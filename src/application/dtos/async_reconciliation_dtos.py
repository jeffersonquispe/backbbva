from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.application.ports.async_execution_inspector_port import (
    AsyncExecutionState,
)
from src.application.ports.async_operation_port import AsyncOperationStatus


@dataclass
class ReconcileAsyncOperationsInput:
    limit: int = 100


@dataclass
class ReconciledAsyncOperationOutput:
    id: UUID
    previous_status: AsyncOperationStatus
    current_status: AsyncOperationStatus
    execution_state: AsyncExecutionState
    detail: str | None = None


@dataclass
class ReconcileAsyncOperationsOutput:
    inspected: int
    updated: int
    operations: list[ReconciledAsyncOperationOutput]
