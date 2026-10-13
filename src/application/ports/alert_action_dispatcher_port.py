from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AlertActionDispatchRef:
    backend: str
    external_id: str | None = None


class AlertActionDispatcher(ABC):
    def dispatch(
        self, action: str, alert_id: UUID, content: str | None = None
    ) -> AlertActionDispatchRef:
        raise NotImplementedError
