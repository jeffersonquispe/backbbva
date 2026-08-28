from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.application.ports.configuration_port import ConfigurationRef


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
    max_feedback_iterations: int = 1
    # Which stored ConfigurationRecord to resolve segments against - kept
    # as its own typed field, not folded into config_overrides, since it
    # selects a whole config (with validation/fail-loud semantics) rather
    # than patching a per-step string. None = today's behavior
    # (ConfigurationRepository.get_active()). See _resolve_segment in
    # alert_review_workflow.py.
    configuration_ref: ConfigurationRef | None = None


@dataclass
class StartAlertWorkflowOutput:
    alert_id: UUID
    async_operation_id: UUID
    workflow_execution_id: UUID
    status: str
