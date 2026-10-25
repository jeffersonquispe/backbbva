from __future__ import annotations

from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True)
class AlertEvent:
    alert_id: str
    event_id: str


@dataclass(frozen=True)
class EventReceipt:
    receipt_id: str
    duplicate: bool = False


class EventPublisherPort(ABC):
    def publish(self, event: AlertEvent) -> EventReceipt:
        raise NotImplementedError


class EventIdConflictError(Exception):
    """An event id was reused for a different alert."""
