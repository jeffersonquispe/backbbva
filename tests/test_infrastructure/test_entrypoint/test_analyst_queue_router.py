from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.dtos.analyst_queue_dtos import (
    AlertDetail,
    AnalystQueueItem,
    InProcessAlertItem,
)
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservation,
)
from src.domain.alerts.entities import (
    AlertRecord,
    AlertStatus,
)
from src.domain.alerts.exceptions import (
    AlertNotFoundError,
    AlertNotHeldByAnalystError,
    AnalystBusyError,
    NoActiveVoicebotCallError,
    NoAnalystCapacityError,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.factories.local_auth_factory import (
    get_current_local_user_use_case,
)
from src.infrastructure.entrypoint.api.factories.operations_factory import (
    get_alert_detail_use_case,
    get_complete_voicebot_call_use_case,
    get_list_analyst_queue_use_case,
    get_list_in_process_alerts_use_case,
    get_release_escalated_alert_use_case,
    get_resolve_escalated_alert_use_case,
    get_take_escalated_alert_use_case,
)
from src.infrastructure.entrypoint.api.routers.analyst_queue_router import (
    router as analyst_queue_router,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.routers.operations_router import (
    router as operations_router,
)

NOW = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)


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
    [
        (AnalystBusyError("other-alert"), "analyst_busy"),
        (NoAnalystCapacityError(), "no_capacity"),
    ],
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


class ScriptedListUseCase:
    def __init__(self, items: list[AnalystQueueItem]) -> None:
        self.items = items

    def execute(self):
        return self.items


def test_queue_lists_the_canonical_alert_and_never_the_raw_payload() -> None:
    user = _user(LocalRole.FRAUD_ANALYST)
    alert = AlertRecord(
        id=uuid4(),
        event_id="evt-1",
        event_type="transfer",
        status=AlertStatus.ESCALATED,
        created_at=NOW,
        updated_at=NOW,
        raw_payload_ref={"bucket": "aria", "key": "alerts/evt-1.json"},
        schema_version=2,
        input={"amount": 5400000, "channel": "digital"},
        labels={"tipo": "ato"},
        history_prev_alerta=[{"amount": 1000}],
        agent_output={"fraud_classification": "ato"},
        configuration_id="cfg",
        configuration_version=7,
    )
    client = _client(user)
    client.app.dependency_overrides[get_list_analyst_queue_use_case] = (
        lambda: ScriptedListUseCase([AnalystQueueItem(alert=alert)])
    )

    response = client.get("/analyst-queue")

    assert response.status_code == 200
    (body,) = response.json()
    assert body["schema_version"] == 2
    assert body["configuration_ref"] == {"configuration_id": "cfg", "version": 7}
    assert body["input"] == {"amount": 5400000, "channel": "digital"}
    assert body["labels"] == {"tipo": "ato"}
    assert body["history_prev_alerta"] == [{"amount": 1000}]
    assert body["agent_output"] == {"fraud_classification": "ato"}
    assert "payload" not in body and "raw_payload_ref" not in body


def _reservation(user: LocalUser, alert_id) -> ResourceReservation:
    return ResourceReservation(
        id="r1",
        resource=ReservedResource.ANALYST,
        alert_id=str(alert_id),
        holder=str(user.id),
        slot=0,
        reserved_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )


class ScriptedUseCase:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result, self.error = result, error
        self.calls: list[tuple] = []

    def execute(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.result


def test_analyst_releases_their_alert() -> None:
    user = _user(LocalRole.FRAUD_ANALYST)
    alert_id = uuid4()
    release = ScriptedUseCase(_reservation(user, alert_id))
    client = _client(user)
    client.app.dependency_overrides[get_release_escalated_alert_use_case] = (
        lambda: release
    )

    response = client.post(f"/analyst-queue/{alert_id}/release")

    assert response.status_code == 200
    assert response.json()["holder_name"] == "Ana Analista"
    assert release.calls == [(str(alert_id), str(user.id))]


def test_release_of_an_alert_not_held_is_a_not_held_conflict() -> None:
    user = _user(LocalRole.FRAUD_ANALYST)
    client = _client(user)
    client.app.dependency_overrides[get_release_escalated_alert_use_case] = (
        lambda: ScriptedUseCase(error=AlertNotHeldByAnalystError("a1"))
    )

    response = client.post(f"/analyst-queue/{uuid4()}/release")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_held"


@pytest.mark.parametrize("path", ["release", "resolve"])
@pytest.mark.parametrize("role", [LocalRole.MANAGER, LocalRole.OPS_ANALYST])
def test_other_roles_cannot_release_or_resolve(path, role) -> None:
    use_case = ScriptedUseCase()
    client = _client(_user(role))
    client.app.dependency_overrides[get_release_escalated_alert_use_case] = (
        lambda: use_case
    )
    client.app.dependency_overrides[get_resolve_escalated_alert_use_case] = (
        lambda: use_case
    )

    response = client.post(
        f"/analyst-queue/{uuid4()}/{path}", json={"decision": "pass", "notes": ""}
    )

    assert response.status_code == 403
    assert use_case.calls == []


def test_analyst_resolves_an_alert_with_a_decision_and_notes() -> None:
    user = _user(LocalRole.FRAUD_ANALYST)
    alert_id = uuid4()
    resolve = ScriptedUseCase(_reservation(user, alert_id))
    client = _client(user)
    client.app.dependency_overrides[get_resolve_escalated_alert_use_case] = (
        lambda: resolve
    )

    response = client.post(
        f"/analyst-queue/{alert_id}/resolve",
        json={"decision": "block", "notes": "confirmado"},
    )

    assert response.status_code == 200
    (call,) = resolve.calls
    assert (call[0].alert_id, call[0].analyst_id) == (str(alert_id), str(user.id))
    assert (call[0].decision, call[0].notes) == ("block", "confirmado")


def test_resolve_rejects_an_unknown_decision() -> None:
    client = _client(_user(LocalRole.FRAUD_ANALYST))

    response = client.post(
        f"/analyst-queue/{uuid4()}/resolve", json={"decision": "ignore"}
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("error", "status_code"),
    [(AlertNotHeldByAnalystError("a"), 409), (AlertNotFoundError("a"), 404)],
)
def test_resolve_errors_map_to_http_codes(error, status_code) -> None:
    client = _client(_user(LocalRole.FRAUD_ANALYST))
    client.app.dependency_overrides[get_resolve_escalated_alert_use_case] = (
        lambda: ScriptedUseCase(error=error)
    )

    response = client.post(
        f"/analyst-queue/{uuid4()}/resolve", json={"decision": "pass"}
    )

    assert response.status_code == status_code


def test_in_process_route_is_not_parsed_as_an_alert_id() -> None:
    alert = AlertRecord(
        id=uuid4(),
        event_id="evt-2",
        event_type="transfer",
        status=AlertStatus.PROCESSING,
        created_at=NOW,
        updated_at=NOW,
        input={"amount": 10},
    )
    client = _client(_user(LocalRole.MANAGER))
    client.app.dependency_overrides[get_list_in_process_alerts_use_case] = (
        lambda: ScriptedListUseCase(
            [
                InProcessAlertItem(
                    alert=alert, workflow_status="RUNNING", current_step="profile"
                )
            ]
        )
    )

    response = client.get("/analyst-queue/in-process")

    assert response.status_code == 200
    (body,) = response.json()
    assert body["alert_id"] == str(alert.id)
    assert body["current_step"] == "profile"
    assert body["workflow_status"] == "RUNNING"
    assert "reservation" not in body


def test_closed_alert_detail_names_the_analyst_and_their_decision() -> None:
    user = _user(LocalRole.FRAUD_ANALYST)
    alert = AlertRecord(
        id=uuid4(),
        event_id="evt-3",
        event_type="transfer",
        status=AlertStatus.CLOSED,
        created_at=NOW,
        updated_at=NOW,
        analyst_resolution={
            "decision": "block",
            "notes": "Cliente confirmó",
            "resolved_by": str(user.id),
            "resolved_at": NOW.isoformat(),
        },
    )
    client = _client(user)
    client.app.dependency_overrides[get_alert_detail_use_case] = lambda: ScriptedUseCase(
        AlertDetail(alert=alert)
    )

    response = client.get(f"/analyst-queue/{alert.id}")

    assert response.status_code == 200
    assert response.json()["analyst_resolution"] == {
        "decision": "block",
        "notes": "Cliente confirmó",
        "resolved_by": str(user.id),
        "resolved_by_name": "Ana Analista",
        "resolved_at": "2026-09-28T15:00:00Z",
    }


def test_detail_without_a_resolution_has_none() -> None:
    alert = AlertRecord(
        id=uuid4(),
        event_id="evt-4",
        event_type="transfer",
        status=AlertStatus.ESCALATED,
        created_at=NOW,
        updated_at=NOW,
    )
    client = _client(_user(LocalRole.FRAUD_ANALYST))
    client.app.dependency_overrides[get_alert_detail_use_case] = lambda: ScriptedUseCase(
        AlertDetail(alert=alert)
    )

    assert client.get(f"/analyst-queue/{alert.id}").json()["analyst_resolution"] is None
