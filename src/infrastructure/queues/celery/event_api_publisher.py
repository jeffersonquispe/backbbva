from __future__ import annotations

from functools import lru_cache

import redis
from celery import Celery

from src.application.ports.event_publisher_port import (
    AlertEvent,
    EventIdConflictError,
    EventPublisherPort,
    EventReceipt,
)
from src.infrastructure.entrypoint.event_api.settings import event_api_settings

TASK_NAME = "events.production.receive"


class CeleryEventPublisher(EventPublisherPort):
    def __init__(self, app: Celery, idempotency_store: redis.Redis, queue: str, ttl: int):
        self._app = app
        self._store = idempotency_store
        self._queue = queue
        self._ttl = ttl

    def publish(self, event: AlertEvent) -> EventReceipt:
        key = f"event-api:receipt:{event.event_id}"
        acquired = self._store.set(key, event.alert_id, nx=True, ex=self._ttl)
        if not acquired:
            existing_alert_id = self._store.get(key)
            if existing_alert_id != event.alert_id:
                raise EventIdConflictError(
                    f"Event id {event.event_id!r} is already used by another alert"
                )
            return EventReceipt(receipt_id=event.event_id, duplicate=True)
        try:
            self._app.send_task(
                TASK_NAME,
                kwargs={"alert_id": event.alert_id, "event_id": event.event_id},
                queue=self._queue,
                task_id=event.event_id,
            )
        except Exception:
            self._store.delete(key)
            raise
        return EventReceipt(receipt_id=event.event_id)


@lru_cache
def get_event_publisher() -> CeleryEventPublisher:
    settings = event_api_settings()
    app = Celery("aria-event-api", broker=settings.celery_broker_url)
    store = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return CeleryEventPublisher(
        app=app,
        idempotency_store=store,
        queue=settings.production_queue,
        ttl=settings.idempotency_ttl_seconds,
    )
