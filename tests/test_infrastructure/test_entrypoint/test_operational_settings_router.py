"""C2: amount tier validation surfaces as 422; omitted tiers are kept."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.ports.operational_settings_port import (
    AmountTier,
    OperationalSettings,
    OperationalSettingsChange,
)
from src.application.use_cases.operational_settings.update_operational_settings import (
    UpdateOperationalSettingsUseCase,
)
from src.infrastructure.entrypoint.api.factories.operational_settings_factory import (
    get_update_operational_settings_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.routers.operational_settings_router import (
    router,
)


class InMemoryOperationalSettingsRepository:
    def __init__(self, settings: OperationalSettings) -> None:
        self.settings = settings
        self.history: list[OperationalSettingsChange] = []

    def get(self) -> OperationalSettings:
        return self.settings

    def update(self, settings, change):
        self.settings = settings
        self.history.append(change)
        return settings

    def list_changes(self, limit: int = 50):
        return list(reversed(self.history))[:limit]


def _client(
    repository: InMemoryOperationalSettingsRepository,
    role: LocalRole = LocalRole.MANAGER,
) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    user = LocalUser(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        email="manager@example.com",
        name="Manager",
        password_hash="",
        role=role,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_update_operational_settings_use_case] = (
        lambda: UpdateOperationalSettingsUseCase(repository)
    )
    return TestClient(app)


def _tier(code, low, high):
    return {"code": code, "label": code, "min_inclusive": low, "max_exclusive": high}


def test_overlapping_tiers_answer_422_and_save_nothing() -> None:
    repository = InMemoryOperationalSettingsRepository(OperationalSettings())
    response = _client(repository).put(
        "/operational-settings",
        json={"settings": {"amount_tiers": [_tier("a", 0, 100), _tier("b", 50, None)]}},
    )
    assert response.status_code == 422
    assert repository.history == []


def test_valid_tiers_are_saved_with_server_side_version() -> None:
    repository = InMemoryOperationalSettingsRepository(OperationalSettings())
    response = _client(repository).put(
        "/operational-settings",
        json={
            "settings": {
                "amount_tiers": [_tier("low", 0, 1000), _tier("high", 1000, None)],
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert [t["code"] for t in body["amount_tiers"]] == ["low", "high"]


def test_request_without_amount_tiers_keeps_current_ones() -> None:
    current = replace(
        OperationalSettings(),
        amount_tiers=[AmountTier("all", "all", 0, None)],
    )
    repository = InMemoryOperationalSettingsRepository(current)
    response = _client(repository).put(
        "/operational-settings", json={"settings": {"agent_enabled": False}}
    )
    assert response.status_code == 200
    assert response.json()["amount_tiers"][0]["code"] == "all"


def test_maturation_settings_round_trip_and_record_diff() -> None:
    repository = InMemoryOperationalSettingsRepository(OperationalSettings())
    response = _client(repository).put(
        "/operational-settings",
        json={
            "settings": {
                "maturing_days": 10,
                "expected_coverage_pct": 97.5,
                "stable_months": 8,
            },
            "changed_by": "manager",
        },
    )

    assert response.status_code == 200
    assert response.json()["maturing_days"] == 10
    assert response.json()["expected_coverage_pct"] == 97.5
    assert response.json()["stable_months"] == 8
    assert {change.path for change in repository.history[0].changes} == {
        "maturing_days",
        "expected_coverage_pct",
        "stable_months",
    }


def test_maturation_settings_out_of_range_return_422() -> None:
    repository = InMemoryOperationalSettingsRepository(OperationalSettings())
    response = _client(repository).put(
        "/operational-settings", json={"settings": {"maturing_days": 366}}
    )

    assert response.status_code == 422
    assert repository.history == []


def test_channel_manager_cannot_update_operational_settings() -> None:
    repository = InMemoryOperationalSettingsRepository(OperationalSettings())
    response = _client(repository, LocalRole.CHANNEL_MANAGER).put(
        "/operational-settings", json={"settings": {"maturing_days": 5}}
    )

    assert response.status_code == 403
    assert repository.history == []
