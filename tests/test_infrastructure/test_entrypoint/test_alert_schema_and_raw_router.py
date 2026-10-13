from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.alert_port import AlertRecord, AlertStatus
from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaFieldType,
    AlertSchemaStatus,
    AlertSchemaVersion,
)
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.ports.object_storage_port import ObjectStorageRef
from src.infrastructure.entrypoint.api.routers import alert_schema_router, alerts_router
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user


class FakeStorage:
    def __init__(self, payload: dict):
        self.payload = payload
        self.audit: list[tuple[str, str]] = []

    def get_bytes(self, key: str) -> bytes:
        return json.dumps(self.payload).encode()

    def put_text(
        self, key: str, content: str, content_type: str = "text/plain"
    ) -> ObjectStorageRef:
        self.audit.append((key, content))
        return ObjectStorageRef("test", key, f"test://{key}")


class FakeAlertRepository:
    def __init__(self, alert: AlertRecord):
        self.alert = alert

    def get(self, alert_id: UUID) -> AlertRecord | None:
        return self.alert if alert_id == self.alert.id else None


def _user(role: LocalRole) -> LocalUser:
    now = datetime.now(UTC)
    return LocalUser(uuid4(), "user@example.com", "User", "x", role, True, now, now)


def _alert(schema_version: int = 1) -> AlertRecord:
    now = datetime.now(UTC)
    alert_id = uuid4()
    return AlertRecord(
        id=alert_id,
        event_id="event-1",
        event_type="payment",
        status=AlertStatus.RECEIVED,
        created_at=now,
        updated_at=now,
        raw_payload_ref=ObjectStorageRef(
            "test", "raw/event-1.json", "test://raw/event-1.json"
        ),
        schema_version=schema_version,
        input={"event_id": "event-1"},
        labels={"fraud": "pending"},
        history_prev_alerta=[],
        agent_output={"score": 0.1},
    )


def _schema() -> AlertSchemaVersion:
    return AlertSchemaVersion(
        version=1,
        status=AlertSchemaStatus.ACTIVE,
        fields=[
            AlertSchemaField(
                id="card",
                data_source=AlertSchemaDataSource.ARIC,
                field="card_number",
                field_ds_loc="payment.card.number.value",
                type=AlertSchemaFieldType.STRING,
                is_sensible=True,
                sensitivity_strategy="obfuscate",
            ),
            AlertSchemaField(
                id="host-only",
                data_source=AlertSchemaDataSource.HOST,
                field="customer_id",
                field_ds_loc="payment.customer_id",
                is_sensible=True,
                sensitivity_strategy="anonymize",
            ),
        ],
    )


def _raw_client(
    user: LocalUser,
    alert: AlertRecord,
    schema: AlertSchemaVersion,
    storage: FakeStorage,
) -> TestClient:
    app = FastAPI()
    app.include_router(alerts_router.router)
    app.dependency_overrides[get_current_user] = lambda: user
    alerts_router.get_alert_repository = lambda: FakeAlertRepository(alert)
    alerts_router.get_alert_schema_repository = lambda: SimpleNamespace(
        get=lambda _: schema
    )
    alerts_router.get_alert_object_storage = lambda: storage
    return TestClient(app)


def test_raw_endpoint_requires_schema_permission() -> None:
    alert = _alert()
    client = _raw_client(
        _user(LocalRole.CHANNEL_MANAGER), alert, _schema(), FakeStorage({})
    )
    assert client.get(f"/alerts/{alert.id}/raw").status_code == 403


def test_raw_endpoint_redacts_aric_nested_list_and_audits_access() -> None:
    alert = _alert()
    storage = FakeStorage(
        {
            "payment": {
                "card": {"number": [{"value": "1234567890123456"}]},
                "customer_id": "host-secret",
            },
        }
    )
    client = _raw_client(_user(LocalRole.MANAGER), alert, _schema(), storage)

    response = client.get(f"/alerts/{alert.id}/raw")

    assert response.status_code == 200
    assert (
        response.json()["payment"]["card"]["number"][0]["value"] == "************3456"
    )
    assert response.json()["payment"]["customer_id"] == "host-secret"
    assert len(storage.audit) == 1
    audit = json.loads(storage.audit[0][1])
    assert audit["alert_id"] == str(alert.id)
    assert audit["user_id"]


def test_raw_endpoint_returns_404_without_a_payload_reference() -> None:
    alert = _alert()
    alert = replace(alert, raw_payload_ref=None)
    client = _raw_client(
        _user(LocalRole.RELEASE_MANAGER), alert, _schema(), FakeStorage({})
    )
    assert client.get(f"/alerts/{alert.id}/raw").status_code == 404


class FakeSchemaUseCase:
    def __init__(self, value):
        self.value = value

    def execute(self, *args, **kwargs):
        return self.value


def _schema_client(role: LocalRole, schema: AlertSchemaVersion | None) -> TestClient:
    app = FastAPI()
    app.include_router(alert_schema_router.router)
    app.dependency_overrides[get_current_user] = lambda: _user(role)
    alert_schema_router.get_get_active_alert_schema_use_case = (
        lambda: FakeSchemaUseCase(schema)
    )
    alert_schema_router.get_list_alert_schema_versions_use_case = (
        lambda: FakeSchemaUseCase([schema] if schema else [])
    )
    return TestClient(app)


def test_active_schema_is_available_to_any_authenticated_role() -> None:
    response = _schema_client(LocalRole.FRAUD_ANALYST, _schema()).get(
        "/alert-schema/active"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"


@pytest.mark.parametrize("role", [LocalRole.FRAUD_ANALYST, LocalRole.CHANNEL_MANAGER])
def test_schema_history_is_restricted_to_read_roles(role: LocalRole) -> None:
    response = _schema_client(role, _schema()).get("/alert-schema/versions")
    assert response.status_code == 403


def test_schema_history_is_readable_by_data_analyst() -> None:
    response = _schema_client(LocalRole.DATA_ANALYST, _schema()).get(
        "/alert-schema/versions"
    )
    assert response.status_code == 200
    assert response.json()[0]["version"] == 1
