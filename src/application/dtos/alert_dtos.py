from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass
class StartAlertWorkflowInput:
    payload: dict[str, Any]
    created_by: str | None = None


@dataclass
class StartAlertWorkflowOutput:
    alert_id: UUID
    async_operation_id: UUID
    workflow_execution_id: UUID
    status: str
