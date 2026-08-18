from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class StartAlertWorkflowInput:
    payload: dict[str, Any]
    created_by: str | None = None
    # Set when this alert is dispatched as part of a batch test run - links
    # the WorkflowExecutionRecord back to its TestRunRecord (see
    # test_run_port.py) and carries the run's prompt/model overrides
    # through to alert_review_workflow.py's per-step config_overrides read.
    test_run_id: UUID | None = None
    config_overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class StartAlertWorkflowOutput:
    alert_id: UUID
    async_operation_id: UUID
    workflow_execution_id: UUID
    status: str
