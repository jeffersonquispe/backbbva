from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.workflow_port import WorkflowExecutionRecord


@dataclass(frozen=True)
class WorkflowExecutionRef:
    backend: str
    external_id: str | None = None


class WorkflowExecutor:
    def start(
        self,
        workflow: WorkflowExecutionRecord,
    ) -> WorkflowExecutionRef:
        raise NotImplementedError
