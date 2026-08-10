from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AlertActionDispatchRef:
    backend: str
    external_id: str | None = None


class AlertActionDispatcher:
    def dispatch(self, action: str, alert_id: UUID) -> AlertActionDispatchRef:
        raise NotImplementedError
