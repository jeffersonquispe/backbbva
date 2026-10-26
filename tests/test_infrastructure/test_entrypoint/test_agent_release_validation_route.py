from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.domain.agents.release import (
    RetrospectiveValidation,
    RetrospectiveValidationStatus,
)
from src.infrastructure.entrypoint.api.factories.agent_release_factory import (
    get_validate_retrospective_release_use_case,
)
from src.infrastructure.entrypoint.api.routers import agent_release_router
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def _validation(status=RetrospectiveValidationStatus.RUNNING):
    return RetrospectiveValidation(
        validation_id="val-1",
        session_id="s1",
        experiment_id="e1",
        status=status,
        snapshot_id="snap",
        snapshot_sha256="a" * 64,
        component_pins=(),
        baseline_component_pins=(),
        evidence={},
        created_by="cm",
        created_by_id="cm-1",
        created_at=NOW,
    )


def _user(role):
    return LocalUser(
        id=UUID(int=1),
        email="u@example.com",
        name="U",
        password_hash="",
        role=role,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def test_validation_starts_in_the_worker_and_answers_accepted(monkeypatch) -> None:
    queued: list[str] = []

    class UseCase:
        def start(self, request):
            return _validation()

    monkeypatch.setattr(
        agent_release_router, "enqueue_retrospective_validation", queued.append
    )
    app = FastAPI()
    app.include_router(agent_release_router.router)
    app.dependency_overrides[get_current_user] = lambda: _user(
        LocalRole.CHANNEL_MANAGER
    )
    app.dependency_overrides[get_validate_retrospective_release_use_case] = UseCase

    response = TestClient(app).post(
        "/agent/releases/retrospective-validations",
        json={"session_id": "s1", "experiment_id": "e1"},
    )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "RUNNING"
    assert queued == ["val-1"]


def test_the_channel_manager_can_follow_its_validation(monkeypatch) -> None:
    class Repository:
        def get_validation(self, validation_id):
            return _validation(RetrospectiveValidationStatus.PASSED)

    app = FastAPI()
    app.include_router(agent_release_router.router)
    app.dependency_overrides[get_current_user] = lambda: _user(
        LocalRole.CHANNEL_MANAGER
    )
    app.dependency_overrides[agent_release_router.get_agent_release_repository] = (
        Repository
    )

    response = TestClient(app).get("/agent/releases/retrospective-validations/val-1")

    assert response.status_code == 200
    assert response.json()["status"] == "PASSED"
