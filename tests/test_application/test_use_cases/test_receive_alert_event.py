from src.application.ports.event_publisher_port import (
    AlertEvent,
    EventPublisherPort,
    EventReceipt,
)
from src.application.use_cases.event_api.receive_alert_event import (
    ReceiveAlertEventUseCase,
)


class RecordingEventPublisher(EventPublisherPort):
    def __init__(self) -> None:
        self.events: list[AlertEvent] = []

    def publish(self, event: AlertEvent) -> EventReceipt:
        self.events.append(event)
        return EventReceipt(receipt_id=event.event_id)


def test_receive_event_publishes_alert_and_event_ids_unchanged() -> None:
    publisher = RecordingEventPublisher()

    receipt = ReceiveAlertEventUseCase(publisher).execute("alert-7", "event-9")

    assert publisher.events == [AlertEvent(alert_id="alert-7", event_id="event-9")]
    assert receipt == EventReceipt(receipt_id="event-9")
