from __future__ import annotations

from src.application.ports.async_execution_inspector_port import (
    AsyncExecutionInspector,
    AsyncExecutionSnapshot,
    AsyncExecutionState,
)
from src.application.ports.async_executor_port import (
    AsyncExecutionRef,
    AsyncExecutor,
)
from src.application.ports.async_operation_port import AsyncOperationRecord
from src.application.ports.workflow_executor_port import (
    WorkflowExecutionRef,
    WorkflowExecutor,
)
from src.domain.workflows.entities import WorkflowExecutionRecord


class DeferredWorkflowExecutor(WorkflowExecutor):
    def start(
        self,
        workflow: WorkflowExecutionRecord,
    ) -> WorkflowExecutionRef:
        return WorkflowExecutionRef(backend="deferred")


class DeferredAsyncExecutor(AsyncExecutor):
    """No-op executor for environments without an async backend."""

    def dispatch(self, operation: AsyncOperationRecord) -> AsyncExecutionRef:
        return AsyncExecutionRef(backend="deferred")


class DeferredAsyncExecutionInspector(AsyncExecutionInspector):
    def inspect(
        self,
        operation: AsyncOperationRecord,
    ) -> AsyncExecutionSnapshot:
        return AsyncExecutionSnapshot(
            state=AsyncExecutionState.UNKNOWN,
            detail="Deferred executor has no backend state",
        )
