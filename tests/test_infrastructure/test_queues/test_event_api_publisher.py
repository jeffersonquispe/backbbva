from __future__ import annotations

import pytest

from src.application.ports.event_publisher_port import (
    AlertEvent,
    EventIdConflictError,
)
from src.infrastructure.queues.celery.event_api_publisher import (
    TASK_NAME,
    CeleryEventPublisher,
)


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key, value, *, nx, ex):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)


class RecordingCeleryApp:
    def __init__(self) -> None:
        self.tasks: list[dict] = []
        self.fail = False

    def send_task(self, name: str, **kwargs) -> None:
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.tasks.append({"name": name, **kwargs})


def test_event_publisher_uses_production_queue_and_deduplicates() -> None:
    app = RecordingCeleryApp()
    store = InMemoryIdempotencyStore()
    publisher = CeleryEventPublisher(app, store, queue="production", ttl=60)
    event = AlertEvent("alert-1", "event-1")

    first = publisher.publish(event)
    retry = publisher.publish(event)

    assert first.duplicate is False
    assert retry.duplicate is True
    assert len(app.tasks) == 1
    assert app.tasks[0] == {
        "name": TASK_NAME,
        "kwargs": {"alert_id": "alert-1", "event_id": "event-1"},
        "queue": "production",
        "task_id": "event-1",
    }


def test_event_publisher_rejects_event_id_collision() -> None:
    publisher = CeleryEventPublisher(
        RecordingCeleryApp(), InMemoryIdempotencyStore(), queue="production", ttl=60
    )
    publisher.publish(AlertEvent("alert-1", "event-1"))

    with pytest.raises(EventIdConflictError):
        publisher.publish(AlertEvent("alert-2", "event-1"))


def test_event_publisher_releases_idempotency_key_when_broker_fails() -> None:
    app = RecordingCeleryApp()
    app.fail = True
    store = InMemoryIdempotencyStore()
    publisher = CeleryEventPublisher(app, store, queue="production", ttl=60)

    with pytest.raises(ConnectionError):
        publisher.publish(AlertEvent("alert-1", "event-1"))

    assert store.values == {}
