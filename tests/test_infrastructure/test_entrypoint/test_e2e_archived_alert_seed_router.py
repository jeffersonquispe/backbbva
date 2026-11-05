from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.infrastructure.entrypoint.api.factories import e2e_factory
from src.infrastructure.entrypoint.api.routers import e2e_router
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

NOW = datetime(2026, 11, 4, tzinfo=UTC)


class RecordingSeed:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self) -> dict[str, str]:
        self.calls += 1
        return {"alert_id": "a1"}


def _client(role: LocalRole, seed: RecordingSeed) -> TestClient:
    user = LocalUser(
        UUID("00000000-0000-0000-0000-000000000001"),
        "u@example.com",
        "U",
        "",
        role,
        True,
        NOW,
        NOW,
    )
    app = FastAPI()
    app.include_router(e2e_router.router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[e2e_router.get_seed_archived_alert] = lambda: seed
    return TestClient(app)


def test_seeding_is_refused_outside_the_local_e2e_environment(monkeypatch) -> None:
    seed = RecordingSeed()
    monkeypatch.setattr(e2e_router.genai_config, "GENAI_ENVIRONMENT", "okd")

    response = _client(LocalRole.MANAGER, seed).post(
        "/e2e/fraud-history/archived-alert"
    )

    assert response.status_code == 404 and seed.calls == 0


def test_seeding_runs_locally_for_roles_that_may_clean_e2e_state(monkeypatch) -> None:
    seed = RecordingSeed()
    monkeypatch.setattr(e2e_router.genai_config, "GENAI_ENVIRONMENT", "local")
    monkeypatch.setattr(e2e_router.genai_config, "E2E_CLEANUP_ENABLED", True)

    allowed = _client(LocalRole.MANAGER, seed).post("/e2e/fraud-history/archived-alert")
    denied = _client(LocalRole.FRAUD_ANALYST, seed).post(
        "/e2e/fraud-history/archived-alert"
    )

    assert allowed.status_code == 200 and allowed.json() == {"alert_id": "a1"}
    assert denied.status_code == 403 and seed.calls == 1


def test_the_seeded_alert_has_fixed_identifiers_for_the_browser_spec() -> None:
    assert e2e_factory.E2E_ARCHIVED_ALERT_ID == "00000000-0000-4000-8000-0000000011c0"
    assert e2e_factory.E2E_ARCHIVED_EVENT_ID == "E2E-11C-ARCHIVED"
