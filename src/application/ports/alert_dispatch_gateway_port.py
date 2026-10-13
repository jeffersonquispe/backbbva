from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AlertDispatchResult:
    alert_id: str
    async_operation_id: str
    workflow_execution_id: str
    status: str


class AlertDispatchGateway(ABC):
    """Crosses the event-simulator microservice's boundary into aria-api's
    real alert-review pipeline (POST /alerts/test) - the only way a
    generated event becomes live traffic. Never wraps
    StartAlertTestWorkflowUseCase in-process: that would reintroduce the
    coupling this service exists to remove (see backend CLAUDE.md /
    simulator design notes - aria-worker's Celery pool must stay isolated
    from simulator load)."""

    @abstractmethod
    def dispatch(
        self, payload: dict, *, created_by: str | None = None
    ) -> AlertDispatchResult: ...
