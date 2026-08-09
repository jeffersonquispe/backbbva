from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AnalystEscalationRef:
    backend: str
    external_id: str | None = None


class AnalystEscalationDispatcher:
    def dispatch(
        self,
        alert_id: UUID,
        workflow_execution_id: UUID,
        event_id: str,
        session_id: str | None,
        reason: str,
    ) -> AnalystEscalationRef:
        raise NotImplementedError
