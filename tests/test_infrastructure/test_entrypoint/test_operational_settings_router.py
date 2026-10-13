"""C2: amount tier validation surfaces as 422; omitted tiers are kept."""

from __future__ import annotations

from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

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


def _client(repository: InMemoryOperationalSettingsRepository) -> TestClient:
    app = FastAPI()
    app.include_router(router)
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
