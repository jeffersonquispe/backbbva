from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservation,
)
from src.domain.alerts.exceptions import (
    AnalystBusyError,
    NoActiveVoicebotCallError,
    NoAnalystCapacityError,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.factories.local_auth_factory import (
    get_current_local_user_use_case,
)
from src.infrastructure.entrypoint.api.factories.operations_factory import (
    get_complete_voicebot_call_use_case,
    get_take_escalated_alert_use_case,
)
from src.infrastructure.entrypoint.api.routers.analyst_queue_router import (
    router as analyst_queue_router,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.routers.operations_router import (
    router as operations_router,
)

NOW = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)


def _user(role: LocalRole) -> LocalUser:
    return LocalUser(
        id=uuid4(),
        email="a@aria.local",
        name="Ana Analista",
        password_hash="x",
        role=role,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class ScriptedTakeUseCase:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def execute(self, alert_id, analyst_id):
        self.calls.append((alert_id, analyst_id))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class NameLookup:
    def __init__(self, user: LocalUser) -> None:
        self._user = user

    def execute(self, user_id):
        return self._user if user_id == self._user.id else None


class RecordingVoicebotUseCase:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple] = []

    def execute(self, alert_id, outcome, detail=None):
        self.calls.append((alert_id, outcome, detail))
        if self.error:
            raise self.error


def _client(user: LocalUser, take=None, voicebot=None) -> TestClient:
    app = FastAPI()
    app.include_router(analyst_queue_router)
    app.include_router(operations_router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_local_user_use_case] = lambda: NameLookup(user)
    if take is not None:
        app.dependency_overrides[get_take_escalated_alert_use_case] = lambda: take
    if voicebot is not None:
        app.dependency_overrides[get_complete_voicebot_call_use_case] = lambda: voicebot
    return TestClient(app)


def test_fraud_analyst_takes_an_alert_and_sees_their_name_on_it() -> None:
    user = _user(LocalRole.FRAUD_ANALYST)
    alert_id = uuid4()
    take = ScriptedTakeUseCase(
        ResourceReservation(
            id="r1",
            resource=ReservedResource.ANALYST,
            alert_id=str(alert_id),
            holder=str(user.id),
            slot=0,
            reserved_at=NOW,
            expires_at=NOW + timedelta(minutes=30),
        )
    )

    response = _client(user, take=take).post(f"/analyst-queue/{alert_id}/take")

    assert response.status_code == 200
    assert response.json()["holder_name"] == "Ana Analista"
    assert take.calls == [(alert_id, str(user.id))]


@pytest.mark.parametrize("role", [LocalRole.MANAGER, LocalRole.OPS_ANALYST])
def test_other_roles_cannot_take_alerts(role) -> None:
    take = ScriptedTakeUseCase(None)

    response = _client(_user(role), take=take).post(f"/analyst-queue/{uuid4()}/take")

    assert response.status_code == 403
    assert take.calls == []


@pytest.mark.parametrize(
    ("error", "code"),
    [(AnalystBusyError("other-alert"), "analyst_busy"), (NoAnalystCapacityError(), "no_capacity")],
)
def test_take_conflicts_carry_a_machine_readable_code(error, code) -> None:
    response = _client(
        _user(LocalRole.FRAUD_ANALYST), take=ScriptedTakeUseCase(error)
    ).post(f"/analyst-queue/{uuid4()}/take")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code


def test_voicebot_callback_frees_the_slot(monkeypatch) -> None:
    monkeypatch.setattr(genai_config, "VOICEBOT_CALLBACK_TOKEN", "")
    voicebot = RecordingVoicebotUseCase()
    alert_id = uuid4()

    response = _client(_user(LocalRole.MANAGER), voicebot=voicebot).post(
        "/voicebot/callbacks", json={"alert_id": str(alert_id), "outcome": "no_answer"}
    )

    assert response.status_code == 204
    assert voicebot.calls == [(str(alert_id), "no_answer", {})]


def test_voicebot_callback_requires_the_token_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(genai_config, "VOICEBOT_CALLBACK_TOKEN", "s3cret")
    voicebot = RecordingVoicebotUseCase()
    client = _client(_user(LocalRole.MANAGER), voicebot=voicebot)
    body = {"alert_id": str(uuid4()), "outcome": "no_answer"}

    assert client.post("/voicebot/callbacks", json=body).status_code == 401
    assert (
        client.post(
            "/voicebot/callbacks", json=body, headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    assert voicebot.calls == []
    assert (
        client.post(
            "/voicebot/callbacks", json=body, headers={"Authorization": "Bearer s3cret"}
        ).status_code
        == 204
    )


def test_voicebot_callback_for_an_unknown_call_is_404(monkeypatch) -> None:
    monkeypatch.setattr(genai_config, "VOICEBOT_CALLBACK_TOKEN", "")
    alert_id = str(uuid4())

    response = _client(
        _user(LocalRole.MANAGER),
        voicebot=RecordingVoicebotUseCase(NoActiveVoicebotCallError(alert_id)),
    ).post("/voicebot/callbacks", json={"alert_id": alert_id, "outcome": "late"})

    assert response.status_code == 404
