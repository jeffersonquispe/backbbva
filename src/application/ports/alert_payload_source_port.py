from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID


class AlertPayloadSource(ABC):
    """Fetch the canonical alert JSON by its opaque Alert API identifier."""

    @abstractmethod
    def fetch_alert(self, alert_id: UUID) -> dict[str, Any]:
        raise NotImplementedError
