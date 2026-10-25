from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.event_publisher_port import (
    AlertEvent,
    EventIdConflictError,
    EventPublisherPort,
    EventReceipt,
)
from src.infrastructure.entrypoint.event_api.app import app as event_api_app
from src.infrastructure.entrypoint.event_api.oidc import get_oidc_verifier
from src.infrastructure.queues.celery.event_api_publisher import get_event_publisher


class AcceptingOidcVerifier:
    def verify(self, token: str) -> dict:
        if token != "valid-token":
            raise ValueError("invalid token")
        return {"sub": "frm"}


class InMemoryEventPublisher(EventPublisherPort):
    def __init__(self) -> None:
        self.events: dict[str, AlertEvent] = {}
        self.fail = False

    def publish(self, event: AlertEvent) -> EventReceipt:
        if self.fail:
            raise ConnectionError("broker down")
        existing = self.events.get(event.event_id)
        if existing is not None:
            if existing.alert_id != event.alert_id:
                raise EventIdConflictError
            return EventReceipt(event.event_id, duplicate=True)
        self.events[event.event_id] = event
        return EventReceipt(event.event_id)


def _client(publisher: InMemoryEventPublisher) -> TestClient:
    app = FastAPI()
    app.mount("/", event_api_app)
    event_api_app.dependency_overrides[get_oidc_verifier] = lambda: AcceptingOidcVerifier()
    event_api_app.dependency_overrides[get_event_publisher] = lambda: publisher
    return TestClient(app)


def test_event_api_accepts_alert_and_deduplicates_same_event_id() -> None:
    publisher = InMemoryEventPublisher()
    client = _client(publisher)
    headers = {"Authorization": "Bearer valid-token"}
    payload = {"alert_id": "alert-1", "event_id": "event-1"}

    first = client.post("/api/event/events", json=payload, headers=headers)
    retry = client.post("/api/event/events", json=payload, headers=headers)

    assert first.status_code == 202
    assert first.json() == {
        "receipt_id": "event-1",
        "status": "accepted",
        "duplicate": False,
    }
    assert retry.status_code == 202
    assert retry.json()["duplicate"] is True
    assert len(publisher.events) == 1


def test_event_api_accepts_extra_frm_summary_fields_but_publishes_only_ids() -> None:
    publisher = InMemoryEventPublisher()
    client = _client(publisher)

    response = client.post(
        "/api/event/events",
        json={
            "alert_id": "alert-1",
            "event_id": "event-1",
            "channel": "card",
            "risk_score": 0.97,
            "transaction": {"amount": 125000},
        },
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 202
    assert publisher.events["event-1"] == AlertEvent("alert-1", "event-1")


def test_event_api_requires_both_identifiers() -> None:
    client = _client(InMemoryEventPublisher())
    headers = {"Authorization": "Bearer valid-token"}

    assert client.post(
        "/api/event/events", json={"event_id": "event-1"}, headers=headers
    ).status_code == 400
    assert client.post(
        "/api/event/events", json={"alert_id": "alert-1"}, headers=headers
    ).status_code == 400


def test_event_api_rejects_missing_or_invalid_oidc_token() -> None:
    client = _client(InMemoryEventPublisher())
    payload = {"alert_id": "alert-1", "event_id": "event-1"}

    assert client.post("/api/event/events", json=payload).status_code == 401
    response = client.post(
        "/api/event/events",
        json=payload,
        headers={"Authorization": "Bearer bad-token"},
    )
    assert response.status_code == 401


def test_event_api_rejects_malformed_json() -> None:
    client = _client(InMemoryEventPublisher())

    response = client.post(
        "/api/event/events",
        content=b"{broken",
        headers={"Authorization": "Bearer valid-token", "Content-Type": "application/json"},
    )

    assert response.status_code == 400


def test_event_api_rejects_oversized_body(monkeypatch) -> None:
    from src.infrastructure.entrypoint.event_api.settings import event_api_settings

    monkeypatch.setattr(event_api_settings(), "max_body_bytes", 16)
    client = _client(InMemoryEventPublisher())

    response = client.post(
        "/api/event/events",
        content=b'{"alert_id":"too-long","event_id":"event-1"}',
        headers={
            "Authorization": "Bearer valid-token",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 413


def test_event_api_rejects_reused_event_id_for_another_alert() -> None:
    publisher = InMemoryEventPublisher()
    publisher.events["event-1"] = AlertEvent("alert-original", "event-1")
    client = _client(publisher)

    response = client.post(
        "/api/event/events",
        json={"alert_id": "alert-other", "event_id": "event-1"},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 409


def test_event_api_returns_retryable_error_when_queue_is_unavailable() -> None:
    publisher = InMemoryEventPublisher()
    publisher.fail = True
    client = _client(publisher)

    response = client.post(
        "/api/event/events",
        json={"alert_id": "alert-1", "event_id": "event-1"},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Production queue unavailable; retry the event"
