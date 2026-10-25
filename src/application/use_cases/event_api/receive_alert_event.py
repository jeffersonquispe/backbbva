from __future__ import annotations

from src.application.ports.event_publisher_port import (
    AlertEvent,
    EventPublisherPort,
    EventReceipt,
)


class ReceiveAlertEventUseCase:
    def __init__(self, publisher: EventPublisherPort) -> None:
        self._publisher = publisher

    def execute(self, alert_id: str, event_id: str) -> EventReceipt:
        return self._publisher.publish(AlertEvent(alert_id=alert_id, event_id=event_id))
