from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from src.application.ports.workflow_status_port import WorkflowStatusUpdate
from src.domain.workflows.entities import (
    WorkflowStatus,
    WorkflowStepStatus,
)
from src.infrastructure.workflows.queued.queued_status_reporter import (
    QueuedWorkflowStatusReporter,
)


class RecordingWorkflowExecutionRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def update(self, workflow_id: UUID, **changes: Any) -> None:
        self.calls.append({"workflow_id": workflow_id, **changes})


class RecordingWorkflowStepExecutionRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def update(
        self, workflow_execution_id: UUID, step_id: UUID, **changes: Any
    ) -> None:
        self.calls.append(
            {
                "workflow_execution_id": workflow_execution_id,
                "step_id": step_id,
                **changes,
            }
        )


def test_coalesces_a_burst_of_updates_into_the_latest_write() -> None:
    workflows = RecordingWorkflowExecutionRepository()
    steps = RecordingWorkflowStepExecutionRepository()
    reporter = QueuedWorkflowStatusReporter(workflows, steps)
    workflow_id = uuid4()

    for i in range(20):
        reporter.report(
            WorkflowStatusUpdate(
                workflow_execution_id=workflow_id,
                status=WorkflowStatus.RUNNING,
                detail={"current_step": f"step_{i}"},
            )
        )
    reporter.flush(timeout=2)
    reporter.stop(timeout=2)

    assert len(workflows.calls) < 20
    assert workflows.calls[-1]["current_step"] == "step_19"


def test_writes_step_update_with_detail_kwargs() -> None:
    workflows = RecordingWorkflowExecutionRepository()
    steps = RecordingWorkflowStepExecutionRepository()
    reporter = QueuedWorkflowStatusReporter(workflows, steps)
    workflow_id = uuid4()
    step_id = uuid4()

    reporter.report(
        WorkflowStatusUpdate(
            workflow_execution_id=workflow_id,
            step_name="pre_process",
            step_id=step_id,
            status=WorkflowStepStatus.SUCCEEDED,
            detail={"output": {"ok": True}},
        )
    )
    reporter.flush(timeout=2)
    reporter.stop(timeout=2)

    assert len(steps.calls) == 1
    call = steps.calls[0]
    assert call["workflow_execution_id"] == workflow_id
    assert call["step_id"] == step_id
    assert call["status"] == WorkflowStepStatus.SUCCEEDED
    assert call["output"] == {"ok": True}


def test_drops_step_update_missing_step_id() -> None:
    workflows = RecordingWorkflowExecutionRepository()
    steps = RecordingWorkflowStepExecutionRepository()
    reporter = QueuedWorkflowStatusReporter(workflows, steps)

    reporter.report(
        WorkflowStatusUpdate(
            workflow_execution_id=uuid4(),
            step_name="pre_process",
            status=WorkflowStepStatus.RUNNING,
        )
    )
    reporter.flush(timeout=2)
    reporter.stop(timeout=2)

    assert steps.calls == []
